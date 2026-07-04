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
from pathlib import Path

# The path layout (MEDIA_ROOT, DATABASES, TELEGRAM_SESSION_NAME, BASE_DIR) lives in Django settings,
# so bootstrap Django before touching any of it. The imports below must follow django.setup().
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "webapp_engine.settings")

import django  # noqa: E402

django.setup()

from django.conf import settings  # noqa: E402

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


def copy_tree_counted(src: Path, dst: Path, dry_run: bool) -> tuple[int, int]:
    """Recursively copy ``src`` into ``dst`` (real files only), returning (file count, byte total).

    Symlinks are skipped so the bundle holds real bytes, not links into the source tree.
    """
    files = 0
    total = 0
    for root, _dirs, names in os.walk(src):
        target_dir = dst / Path(root).relative_to(src)
        if not dry_run:
            target_dir.mkdir(parents=True, exist_ok=True)
        for name in names:
            source = Path(root) / name
            if source.is_symlink() or not source.is_file():
                continue
            files += 1
            try:
                total += source.stat().st_size
            except OSError:
                pass
            if not dry_run:
                shutil.copy2(source, target_dir / name)
    return files, total


def copy_file_counted(src: Path, dst: Path, dry_run: bool) -> tuple[int, int]:
    """Copy a single file, returning (1, size) if it was a real file, else (0, 0)."""
    if src.is_symlink() or not src.is_file():
        return 0, 0
    size = src.stat().st_size
    if not dry_run:
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)
    return 1, size


def export_database(base_dir: Path, dest: Path, dry_run: bool) -> tuple[int, int]:
    """Snapshot the database into the bundle. SQLite only — external engines are reported and skipped."""
    db = settings.DATABASES["default"]
    engine = str(db["ENGINE"])
    if "sqlite3" not in engine:
        backend = engine.rsplit(".", 1)[-1]
        print(f"  database  : SKIPPED — engine is {backend!r}, not a bundleable file.")
        print("              Dump it separately (e.g. pg_dump) and restore on the target; the .env")
        print(f"              in this bundle already points at a {backend!r} database.")
        return 0, 0
    src_name = Path(db["NAME"])
    if not src_name.exists():
        print(f"  database  : SKIPPED — {src_name} not found.")
        return 0, 0
    rel = rel_to_base(src_name, base_dir)
    target = dest / rel
    if dry_run:
        print(f"  database  : {rel}  (VACUUM INTO, ~{human(src_name.stat().st_size)} source)")
        return 1, src_name.stat().st_size
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists():
        target.unlink()
    # VACUUM INTO writes a consistent, defragmented single-file copy even in WAL mode, so the bundle
    # never needs the -wal/-shm sidecars. A private connection keeps Django's own connection untouched.
    conn = sqlite3.connect(str(src_name))
    try:
        conn.execute("VACUUM INTO ?", (str(target),))
    finally:
        conn.close()
    out = target.stat().st_size
    print(f"  database  : {rel}  ({human(out)}, clean snapshot)")
    return 1, out


def export_session(base_dir: Path, dest: Path, dry_run: bool) -> tuple[int, int]:
    """Copy the Telethon session file (and any journal/WAL sidecars) into the bundle."""
    session = Path(f"{settings.TELEGRAM_SESSION_NAME}.session")
    if not session.is_absolute():
        session = base_dir / session
    present = [p for p in [session, *session.parent.glob(session.name + "-*")] if p.is_file()]
    if not present:
        print(f"  session   : SKIPPED — {session.name} not found (no Telegram login yet).")
        return 0, 0
    files = total = 0
    for p in present:
        rel = rel_to_base(p, base_dir)
        n, b = copy_file_counted(p, dest / rel, dry_run)
        files += n
        total += b
    print(f"  session   : {rel_to_base(session, base_dir)}  ({files} file(s), {human(total)})")
    return files, total


def export_configuration(base_dir: Path, dest: Path, dry_run: bool) -> tuple[int, int]:
    """Copy the whole configuration/ directory (.env, env.example, .operations-* baselines/snapshots)."""
    src = base_dir / "configuration"
    if not src.is_dir():
        print("  config    : SKIPPED — configuration/ not found.")
        return 0, 0
    files, total = copy_tree_counted(src, dest / "configuration", dry_run)
    print(f"  config    : configuration/  ({files} files, {human(total)})")
    return files, total


def export_media(base_dir: Path, dest: Path, media_types: list[str], dry_run: bool) -> tuple[int, int]:
    """Copy each selected media type's subdirectory of MEDIA_ROOT into the bundle."""
    media_root = Path(settings.MEDIA_ROOT)
    media_rel = rel_to_base(media_root, base_dir)
    files = total = 0
    for token in media_types:
        sub = MEDIA_DIRS[token]
        src = media_root / sub
        if not src.is_dir():
            print(f"  media     : {token:12s} SKIPPED — {media_rel}/{sub}/ not present")
            continue
        n, b = copy_tree_counted(src, dest / media_rel / sub, dry_run)
        files += n
        total += b
        print(f"  media     : {token:12s} {media_rel}/{sub}/  ({n} files, {human(b)})")
    return files, total


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

    label = "Planning export (dry run)" if args.dry_run else "Exporting"
    selection = ", ".join(media_types) if media_types else "none"
    print(f"{label} of Pulpit installation")
    print(f"  from : {base_dir}")
    print(f"  to   : {dest}")
    print(f"  media: {selection}\n")

    if not args.dry_run:
        dest.mkdir(parents=True, exist_ok=True)

    total_files = total_bytes = 0
    for files, byts in (
        export_database(base_dir, dest, args.dry_run),
        export_session(base_dir, dest, args.dry_run),
        export_configuration(base_dir, dest, args.dry_run),
        export_media(base_dir, dest, media_types, args.dry_run),
    ):
        total_files += files
        total_bytes += byts

    print()
    if args.dry_run:
        print(f"[dry-run] would export {total_files} files ({human(total_bytes)}). Nothing was written.")
        return 0

    print(f"Done. Bundle written to {dest} — {total_files} files, {human(total_bytes)}.")
    print("It mirrors the Pulpit project layout. To apply it to another installation:")
    print(f'    cp -a "{dest}/." /path/to/other/pulpit/')
    print("    (cd /path/to/other/pulpit && python manage.py migrate)")
    print(
        "NOTE: the bundle contains configuration/.env (API keys, SECRET_KEY) and the Telegram session\n"
        "      (full account access). Transfer and store it securely."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
