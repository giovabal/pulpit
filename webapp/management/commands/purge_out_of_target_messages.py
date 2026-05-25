"""Delete messages (and their on-disk media) belonging to channels outside the in-target scope.

A message survives the purge iff its channel is either:

* explicitly marked for crawling (``organization.is_in_target=True`` or
  ``to_inspect=True``) — **regardless** of whether the channel is currently
  flagged ``is_lost`` / ``is_private`` or has a type excluded by the current
  ``DEFAULT_CHANNEL_TYPES`` filter. The marker is the analyst's declaration
  of scope; transient flags shouldn't erase history.
* a forward source for at least one in-target channel (``Message.forwarded_from``
  joins back to an in-target channel). Channels referenced only via ``t.me/``
  mentions are *not* preserved — only forward sources are. The mention-target
  Channel row itself stays in the database (it's used as a dead-leaf node in
  structural analysis); we just don't keep any messages crawled from it.

Unlike the previous ``scripts/delete_unused_messages.py`` (now removed), this
command also deletes the underlying media files from disk so the operation
actually reclaims storage and not just rows.

Usage:
    python manage.py purge_out_of_target_messages --dry-run   # preview
    python manage.py purge_out_of_target_messages             # interactive
    python manage.py purge_out_of_target_messages --yes       # no prompt

Follow up with ``sqlite3 db.sqlite3 "VACUUM;"`` (or the Maintenance section of
the backoffice) to reclaim DB file space.
"""

from __future__ import annotations

from dataclasses import dataclass

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.db.models import Exists, OuterRef, Q
from django.db.models.query import QuerySet

from network.utils import channel_cutoff_q
from webapp.models import (
    Channel,
    ChannelAttribution,
    Message,
    MessageAudio,
    MessageOtherMedia,
    MessagePicture,
    MessageSticker,
    MessageVideo,
)

# Per-model FileField descriptors that hold the actual on-disk payload. Used to
# enumerate files before the cascade-delete makes them unreachable.
_MEDIA_FIELDS: tuple[tuple[type, str], ...] = (
    (MessagePicture, "picture"),
    (MessageVideo, "video"),
    (MessageAudio, "audio"),
    (MessageSticker, "sticker"),
    (MessageOtherMedia, "media_file"),
)


@dataclass(frozen=True)
class PurgeReport:
    candidate_messages: int
    candidate_media_files: int
    deleted_messages: int = 0
    deleted_media_rows: int = 0
    removed_files: int = 0
    failed_files: int = 0
    dry_run: bool = False


def marked_in_target_channels() -> QuerySet[Channel]:
    """Channels the analyst has declared in scope for crawling, regardless of transient flags.

    Includes channels under an in-target organization and those flagged
    ``to_inspect=True`` (crawled for discovery even when not in target).
    Distinct from ``Channel.objects.in_target()``, which *also* filters by
    ``DEFAULT_CHANNEL_TYPES`` and drops ``is_lost`` / ``is_private`` — using
    that for keep-set computation silently nukes history of channels that
    just happen to be lost or of a type outside the current view.
    """
    has_in_target_period = Exists(
        ChannelAttribution.objects.filter(channel=OuterRef("pk"), organization__is_in_target=True)
    )
    return Channel.objects.filter(Q(has_in_target_period) | Q(to_inspect=True))


def find_purgeable_messages() -> QuerySet[Message]:
    """Return the queryset of messages outside the keep-set.

    Two kinds of messages are purgeable:

    * every message of a channel that is not in the keep-set (no in-target
      attribution period, not ``to_inspect``, and not a forward source);
    * the *out-of-period* messages of a kept in-target channel that is not
      ``to_inspect`` — messages dated outside all its in-target periods, e.g.
      left behind after an analyst narrows a period. ``to_inspect`` channels
      keep every message; pure forward-source (out-of-target) channels keep
      every message too.
    """
    marked = marked_in_target_channels()
    marked_ids = set(marked.values_list("id", flat=True))

    # Channels that are sources of forwards landing in marked-in-target channels.
    forward_source_ids = set(
        Message.objects.filter(channel__in=marked, forwarded_from__isnull=False)
        .values_list("forwarded_from_id", flat=True)
        .distinct()
    )

    keep_channel_ids = marked_ids | forward_source_ids
    to_inspect_ids = set(Channel.objects.filter(to_inspect=True).values_list("id", flat=True))
    prune_channel_ids = marked_ids - to_inspect_ids
    out_of_period = Q(channel_id__in=prune_channel_ids) & ~channel_cutoff_q()
    return Message.objects.filter(~Q(channel_id__in=keep_channel_ids) | out_of_period)


def collect_media_files(messages: QuerySet[Message]) -> list[tuple[object, str]]:
    """Capture ``(storage, name)`` for every on-disk file owned by ``messages``.

    Called *before* the bulk row delete so the cascade doesn't make the
    FileField descriptors unreachable. Returns a flat list ready for
    :func:`remove_files`.
    """
    msg_ids = list(messages.values_list("pk", flat=True))
    if not msg_ids:
        return []
    files: list[tuple[object, str]] = []
    for model, field_name in _MEDIA_FIELDS:
        for media in model.objects.filter(message_id__in=msg_ids).iterator(chunk_size=500):
            descriptor = getattr(media, field_name)
            if descriptor and descriptor.name:
                files.append((descriptor.storage, descriptor.name))
    return files


def remove_files(files: list[tuple[object, str]]) -> tuple[int, int]:
    """Delete the captured files from their storage backend; return (removed, failed)."""
    removed = 0
    failed = 0
    for storage, name in files:
        try:
            storage.delete(name)
            removed += 1
        except OSError:
            failed += 1
    return removed, failed


def purge(*, dry_run: bool = False) -> PurgeReport:
    """Drive the purge end-to-end. Returns a :class:`PurgeReport` for the caller."""
    if not marked_in_target_channels().exists():
        raise CommandError(
            "No channels are marked in-target — refusing to proceed (would delete every message). "
            "Mark at least one channel or organisation as in-target before running this command."
        )

    qs = find_purgeable_messages()
    msg_count = qs.count()
    files = collect_media_files(qs)

    if dry_run or msg_count == 0:
        return PurgeReport(
            candidate_messages=msg_count,
            candidate_media_files=len(files),
            dry_run=dry_run,
        )

    with transaction.atomic():
        deleted_total, deleted_by_type = qs.delete()
    deleted_media_rows = sum(
        count for label, count in deleted_by_type.items() if label.startswith("webapp.Message") and "Media" in label
    )

    removed, failed = remove_files(files)
    return PurgeReport(
        candidate_messages=msg_count,
        candidate_media_files=len(files),
        deleted_messages=deleted_by_type.get("webapp.Message", 0),
        deleted_media_rows=deleted_media_rows,
        removed_files=removed,
        failed_files=failed,
    )


class Command(BaseCommand):
    help = (
        "Delete messages and their on-disk media for channels outside the in-target scope. "
        "Run with --dry-run first to preview."
    )

    def add_arguments(self, parser) -> None:
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Report what would be deleted without touching the database or filesystem.",
        )
        parser.add_argument(
            "--yes",
            "-y",
            action="store_true",
            help="Skip the interactive confirmation prompt.",
        )

    def handle(self, *args, **options) -> None:
        dry_run = options["dry_run"]

        # Preview first so the user sees the impact before the prompt.
        preview = purge(dry_run=True)
        self.stdout.write(f"Messages to delete: {preview.candidate_messages:,}")
        self.stdout.write(f"Media files to remove: {preview.candidate_media_files:,}")

        if dry_run:
            self.stdout.write(self.style.NOTICE("Dry run — no changes made."))
            return

        if preview.candidate_messages == 0:
            self.stdout.write(self.style.SUCCESS("Nothing to delete."))
            return

        if not options["yes"]:
            self.stdout.write("")
            answer = input("Proceed with deletion? [yes/N] ").strip().lower()
            if answer not in ("y", "yes"):
                self.stdout.write(self.style.NOTICE("Aborted."))
                return

        report = purge(dry_run=False)
        self.stdout.write(self.style.SUCCESS(f"Deleted {report.deleted_messages:,} messages."))
        self.stdout.write(
            f"Removed {report.removed_files:,} of {report.candidate_media_files:,} media files from disk."
        )
        if report.failed_files:
            self.stdout.write(
                self.style.WARNING(f"{report.failed_files:,} media files could not be removed (see logs).")
            )
        self.stdout.write(
            self.style.NOTICE(
                "Tip: run `VACUUM` (SQLite) or use the Maintenance section of the backoffice to reclaim DB file space."
            )
        )
