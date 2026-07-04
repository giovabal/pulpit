#!/usr/bin/env python3
"""Export a self-contained, drop-in snapshot of this Pulpit installation.

Bundles the database, the Telegram session, every file under ``configuration/``
(``.env`` included), and the selected media types into a destination directory
whose layout mirrors the Pulpit project root. The result is drop-in: copy its
contents over another Pulpit checkout and that installation gains this one's
data, credentials and crawl session, ready to run.

Usage:
    python export_installation.py DEST [--media ALL|TYPE,TYPE,...] [--dry-run] [--force]

Media types (comma-separated, case-insensitive):
    IMAGES  VIDEO  AUDIO  STICKERS  OTHER_MEDIA  PROFILE
    ALL   default — every type          NONE   database + config + session only

Examples:
    python export_installation.py ~/pulpit-backup                     # everything
    python export_installation.py ~/pulpit-backup --media IMAGES,STICKERS
    python export_installation.py ~/pulpit-backup --media NONE --dry-run
"""

from __future__ import annotations

import argparse
import os
import shutil
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path

# The path layout (MEDIA_ROOT, DATABASES, TELEGRAM_SESSION_NAME, BASE_DIR) lives in Django settings,
# so bootstrap Django before touching any of it. The imports below must follow django.setup().
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "webapp_engine.settings")

import django  # noqa: E402

django.setup()

from django.conf import settings  # noqa: E402

# Optional pretty output: the exporter runs anywhere, but when `rich` is importable it renders a
# header panel, live per-file progress bars, a summary table and styled notices. Without it, the
# same information prints as plain lines — no hard dependency, so the script stays portable.
try:
    from rich.console import Console
    from rich.panel import Panel
    from rich.progress import (
        BarColumn,
        DownloadColumn,
        Progress,
        SpinnerColumn,
        TextColumn,
        TimeRemainingColumn,
        TransferSpeedColumn,
    )
    from rich.table import Table

    _console: Console | None = Console()
except ImportError:
    _console = None

# Media-type token → subdirectory of MEDIA_ROOT. Mirrors the five message-media models
# (photos/videos/audios/stickers/others) plus channel profile pictures (channels/<ch>/profile/…).
MEDIA_DIRS: dict[str, str] = {
    "IMAGES": "photos",
    "VIDEO": "videos",
    "AUDIO": "audios",
    "STICKERS": "stickers",
    "OTHER_MEDIA": "others",
    "PROFILE": "channels",
}

# status → (rich style, plain glyph) for the summary rows.
_STATUS: dict[str, tuple[str, str]] = {
    "exported": ("green", "✓ exported"),
    "planned": ("cyan", "• planned"),
    "skipped": ("yellow", "– skipped"),
}


@dataclass
class Result:
    """One line of the export summary: what a step touched and how it went."""

    component: str
    detail: str
    files: int = 0
    nbytes: int = 0
    status: str = "exported"
    note: str = ""


@dataclass
class Report:
    """Accumulated results plus running totals."""

    rows: list[Result] = field(default_factory=list)

    def add(self, result: Result) -> None:
        self.rows.append(result)

    @property
    def total_files(self) -> int:
        return sum(r.files for r in self.rows)

    @property
    def total_bytes(self) -> int:
        return sum(r.nbytes for r in self.rows)


def human(nbytes: int) -> str:
    """Format a byte count as B / KiB / MiB / GiB / TiB."""
    size = float(nbytes)
    for unit in ("B", "KiB", "MiB", "GiB"):
        if size < 1024:
            return f"{int(size)} B" if unit == "B" else f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} TiB"


def resolve_media_types(raw: str) -> list[str]:
    """Turn ``--media`` into an ordered, de-duplicated list of known type tokens."""
    tokens = [t.strip().upper() for t in raw.split(",") if t.strip()]
    if not tokens or "ALL" in tokens:
        return list(MEDIA_DIRS)
    if "NONE" in tokens:
        if len(tokens) > 1:
            raise SystemExit("error: NONE cannot be combined with other media types.")
        return []
    unknown = [t for t in tokens if t not in MEDIA_DIRS]
    if unknown:
        valid = list(MEDIA_DIRS) + ["ALL", "NONE"]
        raise SystemExit(f"error: unknown media type(s) {unknown}. Choose from {valid}.")
    ordered: list[str] = []
    for t in tokens:
        if t not in ordered:
            ordered.append(t)
    return ordered


def rel_to_base(path: Path, base_dir: Path) -> Path:
    """Path of ``path`` relative to the project root, falling back to its bare name if outside it."""
    try:
        return path.resolve().relative_to(base_dir)
    except ValueError:
        return Path(path.name)


def scan_tree(src: Path) -> tuple[int, int]:
    """Walk ``src`` and return (real-file count, byte total) without copying — cheap, metadata only."""
    files = total = 0
    for root, _dirs, names in os.walk(src):
        for name in names:
            p = Path(root) / name
            if p.is_symlink() or not p.is_file():
                continue
            files += 1
            try:
                total += p.stat().st_size
            except OSError:
                pass
    return files, total


def copy_tree(src: Path, dst: Path, on_file=None) -> tuple[int, int]:
    """Recursively copy real files from ``src`` to ``dst``; call ``on_file(size)`` after each.

    Symlinks are skipped so the bundle holds real bytes, not links into the source tree.
    """
    files = total = 0
    for root, _dirs, names in os.walk(src):
        target_dir = dst / Path(root).relative_to(src)
        target_dir.mkdir(parents=True, exist_ok=True)
        for name in names:
            source = Path(root) / name
            if source.is_symlink() or not source.is_file():
                continue
            size = source.stat().st_size
            shutil.copy2(source, target_dir / name)
            files += 1
            total += size
            if on_file:
                on_file(size)
    return files, total


def copy_file(src: Path, dst: Path) -> tuple[int, int]:
    """Copy a single real file, returning (1, size) or (0, 0) if it is not a real file."""
    if src.is_symlink() or not src.is_file():
        return 0, 0
    size = src.stat().st_size
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dst)
    return 1, size


def _status(message: str):
    """A transient spinner while a quick step runs (rich), or a no-op context otherwise."""
    if _console:
        return _console.status(f"[cyan]{message}")

    class _Null:
        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

    return _Null()


def export_database(base_dir: Path, dest: Path, dry_run: bool, report: Report) -> None:
    """Snapshot the database. SQLite only — external engines are reported and skipped."""
    db = settings.DATABASES["default"]
    engine = str(db["ENGINE"])
    if "sqlite3" not in engine:
        backend = engine.rsplit(".", 1)[-1]
        report.add(Result("database", f"{backend} engine", status="skipped", note="dump separately (e.g. pg_dump)"))
        return
    src_name = Path(db["NAME"])
    if not src_name.exists():
        report.add(Result("database", str(src_name), status="skipped", note="file not found"))
        return
    rel = rel_to_base(src_name, base_dir)
    if dry_run:
        report.add(Result("database", str(rel), 1, src_name.stat().st_size, status="planned", note="VACUUM INTO"))
        return
    target = dest / rel
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists():
        target.unlink()
    # VACUUM INTO writes a consistent, defragmented single-file copy even in WAL mode, so the bundle
    # never needs the -wal/-shm sidecars. A private connection keeps Django's own connection untouched.
    with _status(f"Snapshotting database → {rel} (VACUUM INTO)…"):
        conn = sqlite3.connect(str(src_name))
        try:
            conn.execute("VACUUM INTO ?", (str(target),))
        finally:
            conn.close()
    report.add(Result("database", str(rel), 1, target.stat().st_size, note="clean snapshot"))


def export_session(base_dir: Path, dest: Path, dry_run: bool, report: Report) -> None:
    """Copy the Telethon session file (and any journal/WAL sidecars) into the bundle."""
    session = Path(f"{settings.TELEGRAM_SESSION_NAME}.session")
    if not session.is_absolute():
        session = base_dir / session
    present = [p for p in [session, *session.parent.glob(session.name + "-*")] if p.is_file()]
    if not present:
        report.add(Result("session", session.name, status="skipped", note="no Telegram login yet"))
        return
    rel = rel_to_base(session, base_dir)
    if dry_run:
        report.add(Result("session", str(rel), len(present), sum(p.stat().st_size for p in present), status="planned"))
        return
    files = total = 0
    with _status(f"Copying Telegram session → {rel}…"):
        for p in present:
            n, b = copy_file(p, dest / rel_to_base(p, base_dir))
            files += n
            total += b
    report.add(Result("session", str(rel), files, total))


def export_configuration(base_dir: Path, dest: Path, dry_run: bool, report: Report) -> None:
    """Copy the whole configuration/ directory (.env, env.example, .operations-* baselines/snapshots)."""
    src = base_dir / "configuration"
    if not src.is_dir():
        report.add(Result("config", "configuration/", status="skipped", note="directory not found"))
        return
    if dry_run:
        n, b = scan_tree(src)
        report.add(Result("config", "configuration/", n, b, status="planned"))
        return
    with _status("Copying configuration files…"):
        files, total = copy_tree(src, dest / "configuration")
    report.add(Result("config", "configuration/", files, total))


def export_media(base_dir: Path, dest: Path, media_types: list[str], dry_run: bool, report: Report) -> None:
    """Copy each selected media type's subdirectory of MEDIA_ROOT, with a live progress bar per type."""
    media_root = Path(settings.MEDIA_ROOT)
    media_rel = rel_to_base(media_root, base_dir)

    # Pre-scan so we know per-type totals (drives the dry-run report and the progress bars' size/ETA).
    plans: list[tuple[str, str, Path, int, int]] = []
    for token in media_types:
        sub = MEDIA_DIRS[token]
        src = media_root / sub
        if not src.is_dir():
            report.add(Result("media", f"{token} · {media_rel}/{sub}/", status="skipped", note="not present"))
            continue
        n, b = scan_tree(src)
        plans.append((token, sub, src, n, b))

    if dry_run:
        for token, sub, _src, n, b in plans:
            report.add(Result("media", f"{token} · {media_rel}/{sub}/", n, b, status="planned"))
        return

    if _console and plans:
        with Progress(
            SpinnerColumn(),
            TextColumn("[bold blue]{task.description}"),
            BarColumn(),
            "[progress.percentage]{task.percentage:>3.0f}%",
            DownloadColumn(),
            TransferSpeedColumn(),
            TimeRemainingColumn(),
            console=_console,
        ) as progress:
            for token, sub, src, n, b in plans:
                task = progress.add_task(f"{token:<11} {media_rel}/{sub}/", total=b or 1)
                copy_tree(src, dest / media_rel / sub, on_file=lambda size, t=task: progress.update(t, advance=size))
                progress.update(task, completed=b or 1)
                report.add(Result("media", f"{token} · {media_rel}/{sub}/", n, b))
    else:
        for token, sub, src, n, b in plans:
            copy_tree(src, dest / media_rel / sub)
            print(f"  media    : {token:<12} {media_rel}/{sub}/  ({n} files, {human(b)})")
            report.add(Result("media", f"{token} · {media_rel}/{sub}/", n, b))


def render_header(base_dir: Path, dest: Path, selection: str, dry_run: bool) -> None:
    title = "Planning Pulpit export (dry run)" if dry_run else "Exporting Pulpit installation"
    if _console:
        body = f"[dim]from [/] {base_dir}\n[dim]to   [/] {dest}\n[dim]media[/] {selection}"
        _console.print(Panel(body, title=f"📦 {title}", border_style="cyan", expand=False))
    else:
        print(title)
        print(f"  from : {base_dir}")
        print(f"  to   : {dest}")
        print(f"  media: {selection}\n")


def render_summary(report: Report) -> None:
    if _console:
        table = Table(title="Export summary", title_style="bold", header_style="bold", expand=False)
        table.add_column("Component")
        table.add_column("Detail", overflow="fold")
        table.add_column("Files", justify="right")
        table.add_column("Size", justify="right")
        table.add_column("Status")
        for r in report.rows:
            style, glyph = _STATUS.get(r.status, ("white", r.status))
            detail = r.detail if not r.note else f"{r.detail}  [dim]({r.note})[/]"
            table.add_row(
                r.component,
                detail,
                str(r.files) if r.files else "—",
                human(r.nbytes) if r.nbytes else "—",
                f"[{style}]{glyph}[/]",
            )
        table.add_section()
        table.add_row(
            "[bold]total[/]", "", f"[bold]{report.total_files}[/]", f"[bold]{human(report.total_bytes)}[/]", ""
        )
        _console.print(table)
    else:
        for r in report.rows:
            _, glyph = _STATUS.get(r.status, ("", r.status))
            note = f" ({r.note})" if r.note else ""
            print(f"  {r.component:9s}: {r.detail}{note}  [{r.files} files, {human(r.nbytes)}] {glyph}")
        print(f"  {'total':9s}: {report.total_files} files, {human(report.total_bytes)}")


def render_footer(dest: Path) -> None:
    steps = f'cp -a "{dest}/." /path/to/other/pulpit/\n(cd /path/to/other/pulpit && python manage.py migrate)'
    warning = (
        "This bundle contains configuration/.env (API keys, SECRET_KEY) and the\n"
        "Telegram session (full account access). Transfer and store it securely."
    )
    if _console:
        _console.print(Panel(steps, title="[green]✓ Drop-in ready — apply with[/]", border_style="green", expand=False))
        _console.print(Panel(warning, title="[yellow]⚠ Sensitive data[/]", border_style="yellow", expand=False))
    else:
        print("\nDrop-in ready. Apply it to another Pulpit installation with:")
        print(f'    cp -a "{dest}/." /path/to/other/pulpit/')
        print("    (cd /path/to/other/pulpit && python manage.py migrate)")
        print("NOTE: contains .env secrets and the Telegram session — transfer securely.")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Export a drop-in snapshot of this Pulpit installation "
        "(database + Telegram session + configuration + selected media).",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("dest", type=Path, help="Destination directory for the export bundle.")
    parser.add_argument(
        "--media",
        default="ALL",
        help="Media to include: ALL (default), NONE, or a comma list of "
        "IMAGES,VIDEO,AUDIO,STICKERS,OTHER_MEDIA,PROFILE.",
    )
    parser.add_argument("--dry-run", action="store_true", help="Show what would be exported without writing.")
    parser.add_argument(
        "--force", action="store_true", help="Export into DEST even if it already exists and is non-empty."
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    base_dir = Path(settings.BASE_DIR).resolve()
    dest = args.dest.resolve()
    media_types = resolve_media_types(args.media)

    if dest == base_dir or base_dir in dest.parents or dest in base_dir.parents:
        raise SystemExit(
            f"error: destination {dest} overlaps the Pulpit project directory {base_dir}. "
            "Choose a location outside the project tree."
        )
    if dest.exists() and any(dest.iterdir()) and not args.force:
        raise SystemExit(f"error: {dest} already exists and is not empty. Re-run with --force to export into it.")

    selection = ", ".join(media_types) if media_types else "none (database + config + session only)"
    render_header(base_dir, dest, selection, args.dry_run)

    if not args.dry_run:
        dest.mkdir(parents=True, exist_ok=True)

    report = Report()
    export_database(base_dir, dest, args.dry_run, report)
    export_session(base_dir, dest, args.dry_run, report)
    export_configuration(base_dir, dest, args.dry_run, report)
    export_media(base_dir, dest, media_types, args.dry_run, report)

    render_summary(report)

    if args.dry_run:
        msg = f"Dry run — would export {report.total_files} files ({human(report.total_bytes)}). Nothing was written."
        if _console:
            _console.print(f"[dim]{msg}[/]")
        else:
            print(msg)
        return 0

    render_footer(dest)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
