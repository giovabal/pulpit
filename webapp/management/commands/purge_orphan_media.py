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

Usage:
    python manage.py purge_orphan_media --dry-run   # preview
    python manage.py purge_orphan_media             # interactive
    python manage.py purge_orphan_media --yes       # no prompt
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from dataclasses import dataclass
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


@dataclass(frozen=True)
class OrphanReport:
    candidate_files: int
    candidate_bytes: int
    removed_files: int = 0
    removed_bytes: int = 0
    failed_files: int = 0
    empty_dirs_removed: int = 0
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
    for dirpath, dirnames, filenames in os.walk(root, topdown=False):
        if Path(dirpath) == root:
            continue
        if dirnames or filenames:
            continue
        try:
            os.rmdir(dirpath)
            removed += 1
        except OSError:
            pass
    return removed


def purge_orphans(*, dry_run: bool = False) -> OrphanReport:
    """Find — and, unless ``dry_run`` is set, delete — every orphan file."""
    roots = [r for r in scan_roots() if r.is_dir()]
    if not roots:
        return OrphanReport(candidate_files=0, candidate_bytes=0, dry_run=dry_run)

    candidates: list[tuple[Path, int]] = []
    for path in iter_orphan_files():
        try:
            size = path.stat().st_size
        except OSError:
            size = 0
        candidates.append((path, size))

    total_files = len(candidates)
    total_bytes = sum(size for _, size in candidates)

    if dry_run or total_files == 0:
        return OrphanReport(candidate_files=total_files, candidate_bytes=total_bytes, dry_run=dry_run)

    removed_files = 0
    removed_bytes = 0
    failed_files = 0
    for path, size in candidates:
        try:
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
        if report.empty_dirs_removed:
            self.stdout.write(f"Cleaned up {report.empty_dirs_removed:,} empty directories.")
