"""Remove media files on disk that no row in the database references any more.

Companion to ``purge_out_of_target_messages``: that command deletes messages
and their related media files in step, but every previous deletion path
(crashed crawler runs, interrupted imports, the buggy ``delete_unused_messages``
script that left payloads behind) can have produced orphan files. This command
walks the on-disk directories that hold media payloads and removes anything
that isn't pointed to by one of the seven file-bearing model fields:

* ``MessagePicture.picture`` (under ``photos/``)
* ``MessageVideo.video`` (under ``videos/``)
* ``MessageAudio.audio`` (under ``audios/``)
* ``MessageSticker.sticker`` (under ``stickers/``)
* ``MessageOtherMedia.media_file`` (under ``others/``)
* ``ProfilePicture.picture`` (under ``channels/<X>/profile/``)
* ``ProfilePicture.thumbnail`` (under ``channels/<X>/profile/``)

Anything outside these six roots is untouched. Symlinks are skipped. Empty
directories left behind by the cleanup are removed at the end.

Safe to run while a crawl is downloading media. The referenced-path snapshot is
taken before the walk, so two guards cover what a crawl does meanwhile: a file
written or moved into place within ``RECENT_FILE_GRACE_SECONDS`` (one hour) is
never a candidate — the crawler writes a download to its final path a moment
before saving the row that references it — and each candidate is re-checked
against the database right before it is unlinked, so a row saved (or a new
message linked to an already-stored file) after the snapshot keeps its file.

Usage:
    python manage.py purge_orphan_media --dry-run   # preview
    python manage.py purge_orphan_media             # interactive
    python manage.py purge_orphan_media --yes       # no prompt
"""

from __future__ import annotations

import os
import time
from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from itertools import batched
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand

from webapp.models import (
    MessageAudio,
    MessageOtherMedia,
    MessagePicture,
    MessageSticker,
    MessageVideo,
    ProfilePicture,
)

# (model, FileField name) for every model that stores an actual on-disk payload.
# Each entry contributes one query that materialises ``field.name`` strings (the
# relative-to-MEDIA_ROOT POSIX path Django writes there) into the referenced set.
_REFERENCED_FIELDS: tuple[tuple[type, str], ...] = (
    (MessagePicture, "picture"),
    (MessageVideo, "video"),
    (MessageAudio, "audio"),
    (MessageSticker, "sticker"),
    (MessageOtherMedia, "media_file"),
    (ProfilePicture, "picture"),
    (ProfilePicture, "thumbnail"),
)

# Files written or moved into place within this many seconds are left alone: a
# running crawl writes each download to its final path a moment before it saves
# the row that references it, and a large video can take minutes to write. An
# hour is far above that gap; anything skipped is reclaimed by the next run.
RECENT_FILE_GRACE_SECONDS = 3600

# File names per query when re-checking candidates against the database, well
# under SQLite's bound-variable limit (Django does not split IN lists there).
_RECHECK_CHUNK = 500


@dataclass(frozen=True)
class OrphanReport:
    candidate_files: int
    candidate_bytes: int
    removed_files: int = 0
    removed_bytes: int = 0
    failed_files: int = 0
    empty_dirs_removed: int = 0
    skipped_recent: int = 0
    skipped_referenced: int = 0
    dry_run: bool = False


# Directories the cleanup is scoped to. Profile pictures still live under
# ``channels/<X>/profile/``; message media (shared per Telegram object id) moved
# out of ``channels/`` and into top-level type-keyed dirs in migration 0045.
_SCAN_ROOTS: tuple[str, ...] = ("channels", "photos", "videos", "audios", "stickers", "others")


def scan_roots() -> list[Path]:
    """Absolute paths of the directories the cleanup is scoped to."""
    media_root = Path(settings.MEDIA_ROOT)
    return [media_root / name for name in _SCAN_ROOTS]


def collect_referenced_paths() -> set[str]:
    """Return the POSIX-form, MEDIA_ROOT-relative path of every referenced file."""
    referenced: set[str] = set()
    for model, field in _REFERENCED_FIELDS:
        for name in model.objects.exclude(**{field: ""}).values_list(field, flat=True):
            if name:
                referenced.add(name)
    return referenced


def referenced_among(names: Iterable[str]) -> set[str]:
    """The subset of ``names`` (MEDIA_ROOT-relative POSIX paths) some row references right now.

    Batched by ``_RECHECK_CHUNK`` names per query; also used by
    ``purge_out_of_target_messages`` for its own last-moment re-check.
    """
    found: set[str] = set()
    for chunk in batched(names, _RECHECK_CHUNK):
        for model, field in _REFERENCED_FIELDS:
            found.update(model.objects.filter(**{f"{field}__in": chunk}).values_list(field, flat=True))
    return found


def recently_modified(st: os.stat_result, grace_seconds: float) -> bool:
    """True when the file behind ``st`` was written or moved into place within ``grace_seconds``.

    Takes the later of mtime and ctime — a rename or a new hard link bumps only
    the latter. ``grace_seconds <= 0`` disables the check.
    """
    return grace_seconds > 0 and max(st.st_mtime, st.st_ctime) > time.time() - grace_seconds


def iter_orphan_files() -> Iterator[Path]:
    """Yield absolute paths of files under any scan root with no DB reference."""
    roots = [r for r in scan_roots() if r.is_dir()]
    if not roots:
        return
    referenced = collect_referenced_paths()
    media_root = Path(settings.MEDIA_ROOT)
    for root in roots:
        for path in root.rglob("*"):
            # ``is_file()`` follows symlinks; check ``is_symlink()`` first so we
            # never delete a link's target (only the link itself, and even that
            # we skip to stay conservative).
            if path.is_symlink() or not path.is_file():
                continue
            rel = path.relative_to(media_root).as_posix()
            if rel not in referenced:
                yield path


def _remove_empty_dirs(root: Path) -> int:
    """Bottom-up rmdir of every empty subdirectory under ``root`` (keeps ``root`` itself)."""
    removed = 0
    for dirpath, _dirnames, _filenames in os.walk(root, topdown=False):
        if Path(dirpath) == root:
            continue
        # No dirnames/filenames pre-check: with topdown=False those lists were
        # scanned *before* this walk removed any child directories, so a parent
        # that just became empty would be skipped. rmdir itself is the emptiness
        # test — it fails (and is ignored) on anything still occupied.
        try:
            os.rmdir(dirpath)
            removed += 1
        except OSError:
            pass
    return removed


def purge_orphans(*, dry_run: bool = False, grace_seconds: float = RECENT_FILE_GRACE_SECONDS) -> OrphanReport:
    """Find — and, unless ``dry_run`` is set, delete — every orphan file.

    Files modified within ``grace_seconds`` are skipped (``skipped_recent``), and
    each candidate is re-checked against the database right before it is unlinked
    (``skipped_referenced``): see the module docstring.
    """
    roots = [r for r in scan_roots() if r.is_dir()]
    if not roots:
        return OrphanReport(candidate_files=0, candidate_bytes=0, dry_run=dry_run)

    candidates: list[tuple[Path, int]] = []
    skipped_recent = 0
    for path in iter_orphan_files():
        try:
            st = path.stat()
        except OSError:
            continue  # gone (or unreadable) since the walk listed it: nothing to vet
        if recently_modified(st, grace_seconds):
            skipped_recent += 1
            continue
        candidates.append((path, st.st_size))

    total_files = len(candidates)
    total_bytes = sum(size for _, size in candidates)

    if dry_run or total_files == 0:
        return OrphanReport(
            candidate_files=total_files, candidate_bytes=total_bytes, skipped_recent=skipped_recent, dry_run=dry_run
        )

    media_root = Path(settings.MEDIA_ROOT)
    removed_files = 0
    removed_bytes = 0
    failed_files = 0
    skipped_referenced = 0
    for batch in batched(candidates, _RECHECK_CHUNK):
        # The snapshot predates the walk: a crawl may since have saved a row for one of
        # these files (or linked a new message to it via ``_existing_sibling_file``), or
        # be rewriting it. Re-check both, a batch at a time, right before unlinking.
        names = {path: path.relative_to(media_root).as_posix() for path, _ in batch}
        still_referenced = referenced_among(names.values())
        for path, size in batch:
            if names[path] in still_referenced:
                skipped_referenced += 1
                continue
            try:
                if recently_modified(path.stat(), grace_seconds):
                    skipped_recent += 1
                    continue
                path.unlink()
            except OSError:
                failed_files += 1
                continue
            removed_files += 1
            removed_bytes += size

    empty_dirs = 0
    for root in roots:
        empty_dirs += _remove_empty_dirs(root)

    return OrphanReport(
        candidate_files=total_files,
        candidate_bytes=total_bytes,
        removed_files=removed_files,
        removed_bytes=removed_bytes,
        failed_files=failed_files,
        empty_dirs_removed=empty_dirs,
        skipped_recent=skipped_recent,
        skipped_referenced=skipped_referenced,
    )


def fmt_bytes(n: int) -> str:
    """Human-friendly byte size; mirrors the UI's ``fmtBytes`` JS helper."""
    units = ("B", "KB", "MB", "GB", "TB")
    v = float(n)
    i = 0
    while v >= 1024 and i < len(units) - 1:
        v /= 1024
        i += 1
    return f"{v:.0f} {units[i]}" if (v >= 100 or i == 0) else f"{v:.2f} {units[i]}"


class Command(BaseCommand):
    help = (
        "Delete media files under MEDIA_ROOT's media subdirectories (channels, photos, "
        "videos, audios, stickers, others) that have no corresponding row in the database. "
        f"Files modified within the last {RECENT_FILE_GRACE_SECONDS // 60} minutes are left alone, and each "
        "file is re-checked against the database right before deletion, so it is safe to run during a crawl. "
        "Run --dry-run first to preview."
    )

    def add_arguments(self, parser) -> None:
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Report what would be deleted without touching the filesystem.",
        )
        parser.add_argument(
            "--yes",
            "-y",
            action="store_true",
            help="Skip the interactive confirmation prompt.",
        )

    def handle(self, *args, **options) -> None:
        dry_run = options["dry_run"]
        preview = purge_orphans(dry_run=True)
        self.stdout.write(f"Orphan files: {preview.candidate_files:,}")
        self.stdout.write(f"Disk space to reclaim: {fmt_bytes(preview.candidate_bytes)}")
        if preview.skipped_recent:
            self.stdout.write(
                f"Skipping {preview.skipped_recent:,} unreferenced files modified within the last "
                f"{RECENT_FILE_GRACE_SECONDS // 60} minutes (a crawl may still be saving them)."
            )

        if dry_run:
            self.stdout.write(self.style.NOTICE("Dry run — no changes made."))
            return

        if preview.candidate_files == 0:
            self.stdout.write(self.style.SUCCESS("Nothing to delete."))
            return

        if not options["yes"]:
            self.stdout.write("")
            answer = input("Proceed with deletion? [yes/N] ").strip().lower()
            if answer not in ("y", "yes"):
                self.stdout.write(self.style.NOTICE("Aborted."))
                return

        report = purge_orphans(dry_run=False)
        self.stdout.write(
            self.style.SUCCESS(f"Removed {report.removed_files:,} files ({fmt_bytes(report.removed_bytes)}).")
        )
        if report.failed_files:
            self.stdout.write(self.style.WARNING(f"{report.failed_files:,} files could not be removed."))
        if report.skipped_referenced:
            self.stdout.write(f"Kept {report.skipped_referenced:,} files a database row started referencing meanwhile.")
        if report.empty_dirs_removed:
            self.stdout.write(f"Cleaned up {report.empty_dirs_removed:,} empty directories.")
