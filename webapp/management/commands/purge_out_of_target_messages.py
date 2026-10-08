"""Delete messages (and their on-disk media) belonging to channels outside the in-target scope.

A message survives the purge iff its channel is either:

* explicitly marked for crawling (holds an in-target ``Label``,
  ``to_inspect=True``, or an ``environment_depth`` stamped by the crawler's
  environment pass) — **regardless** of whether the channel is currently
  flagged ``is_lost`` / ``is_private`` or has a type excluded by the current
  ``DEFAULT_CHANNEL_TYPES`` filter. The marker is the analyst's declaration
  of scope (or, for the environment, the crawler's deliberate reach);
  transient flags shouldn't erase history.
* a forward source for at least one in-target channel (``Message.forwarded_from``
  joins back to an in-target channel). Channels referenced only via ``t.me/``
  mentions are *not* preserved — only forward sources are. The mention-target
  Channel row itself stays in the database (it's used as a dead-leaf node in
  structural analysis); we just don't keep any messages crawled from it.

Whatever its channel, a message carrying a message tag (``TaggedMessage`` — the
tagged post or any share of it) is never purged, together with the other
messages of its Telegram album: tagging is the analyst's declaration that this
post matters.

The command also deletes the underlying media files from disk so the operation
actually reclaims storage and not just rows. A file is unlinked only when, right
before unlinking, no row references it any more and it has not been modified
within ``purge_orphan_media.RECENT_FILE_GRACE_SECONDS`` — a crawl running
meanwhile may have linked a new message to the shared path or be re-downloading
it. A file skipped that way and left unreferenced is reclaimed later by
``purge_orphan_media``.

Every statement binds at most ``_CHUNK_SIZE`` values: the candidate pks are
snapshotted once and swept in chunks, so the purge also runs on corpora with
more candidates than SQLite binds per statement.

Usage:
    python manage.py purge_out_of_target_messages --dry-run   # preview
    python manage.py purge_out_of_target_messages             # interactive
    python manage.py purge_out_of_target_messages --yes       # no prompt

Follow up with ``sqlite3 db.sqlite3 "VACUUM;"`` (or the Maintenance section of
the backoffice) to reclaim DB file space.
"""

from __future__ import annotations

import os
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass
from itertools import batched

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.db.models import Count, Exists, OuterRef, Q
from django.db.models.query import QuerySet

from crawler import coverage
from network.utils import channel_cutoff_q
from webapp.management.commands.purge_orphan_media import (
    RECENT_FILE_GRACE_SECONDS,
    recently_modified,
    referenced_among,
)
from webapp.models import (
    Channel,
    ChannelLabel,
    Message,
    MessageAudio,
    MessageOtherMedia,
    MessagePicture,
    MessageSticker,
    MessageVideo,
    TaggedMessage,
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

# Message pks / file names per statement. Django does not split IN lists on
# SQLite, whose bound-variable limit (SQLITE_MAX_VARIABLE_NUMBER: 32,766 on stock
# builds, 999 on old ones) would otherwise cap the size of a purge.
_CHUNK_SIZE = 500


@dataclass(frozen=True)
class PurgeReport:
    candidate_messages: int
    candidate_media_files: int
    deleted_messages: int = 0
    deleted_media_rows: int = 0
    removed_files: int = 0
    failed_files: int = 0
    skipped_files: int = 0
    dry_run: bool = False


def marked_in_target_channels() -> QuerySet[Channel]:
    """Channels the analyst has declared in scope for crawling, regardless of transient flags.

    Includes channels holding an in-target label, those flagged
    ``to_inspect=True`` (crawled for discovery even when not in target), and
    those reached by ``crawl_channels --environment`` (``environment_depth``
    set — crawled deliberately as the scope's citation neighbourhood).
    Distinct from ``Channel.objects.in_target()``, which *also* filters by
    ``DEFAULT_CHANNEL_TYPES`` and drops ``is_lost`` / ``is_private`` — using
    that for keep-set computation silently nukes history of channels that
    just happen to be lost or of a type outside the current view.
    """
    has_in_target_period = Exists(ChannelLabel.objects.filter(channel=OuterRef("pk"), label__is_in_target=True))
    return Channel.objects.filter(Q(has_in_target_period) | Q(to_inspect=True) | Q(environment_depth__isnull=False))


def _tag_shield() -> Q:
    """Messages carrying a tag, and the other messages of a tagged message's album."""
    tagged = Exists(TaggedMessage.objects.filter(message=OuterRef("pk")))
    # A NULL grouped_id never equals the outer row's, so ungrouped messages match only via ``tagged``.
    tagged_album = Exists(
        TaggedMessage.objects.filter(
            message__channel_id=OuterRef("channel_id"), message__grouped_id=OuterRef("grouped_id")
        )
    )
    return Q(tagged) | Q(tagged_album)


def find_purgeable_messages() -> QuerySet[Message]:
    """Return the queryset of messages outside the keep-set.

    Two kinds of messages are purgeable:

    * every message of a channel that is not in the keep-set (no in-target
      label period, not ``to_inspect``, and not a forward source);
    * the *out-of-period* messages of a kept in-target channel that is neither
      ``to_inspect`` nor an environment channel — messages dated outside all its
      in-target periods, e.g. left behind after an analyst narrows a period.
      ``to_inspect`` and environment channels keep every message (the
      environment pass stores by its own window, not by label periods); pure
      forward-source (out-of-target) channels keep every message too.

    Tagged messages are exempt from both, and so are their album siblings — the
    post card shows an album's media through its head, so purging the tails
    would strip a tagged album of its pictures.

    The channel sets stay subqueries, never id lists: a large corpus can hold
    more channels than SQLite binds per statement.
    """
    marked = marked_in_target_channels()
    # Channels that are sources of forwards landing in marked-in-target channels.
    # ``isnull=False`` matters: one NULL in a NOT IN subquery would keep every message.
    forward_sources = Message.objects.filter(channel__in=marked, forwarded_from__isnull=False).values(
        "forwarded_from_id"
    )
    outside_keep_set = ~Q(channel__in=marked) & ~Q(channel_id__in=forward_sources)
    # Marked channels that keep only their in-period messages: not to_inspect, not environment.
    prune_channels = marked.exclude(Q(to_inspect=True) | Q(environment_depth__isnull=False))
    # A dateless message can't be placed inside or outside a period; ~channel_cutoff_q()
    # is vacuously true for it, so guard with date__isnull=False to keep such messages
    # of in-target channels (matching the per-channel detail view, which keeps them).
    out_of_period = Q(channel__in=prune_channels) & Q(date__isnull=False) & ~channel_cutoff_q()
    return Message.objects.filter(outside_keep_set | out_of_period).exclude(_tag_shield())


def trim_history_coverage(channel_ids: set[int]) -> None:
    """Drop the purged days from these channels' ``Channel.history_coverage``.

    The crawler walks only the required days missing from a channel's coverage, so days
    whose messages the purge deleted must leave it — else a period re-extended over them
    later would never fetch those messages again. A channel keeps its in-target days (the
    out-of-period sweep deletes the rest); a channel outside the keep-set keeps none.
    """
    for chunk in batched(sorted(channel_ids), _CHUNK_SIZE):
        periods: dict[int, list] = {}
        for channel_id, start, end in ChannelLabel.objects.filter(
            channel_id__in=chunk, label__is_in_target=True
        ).values_list("channel_id", "start", "end"):
            periods.setdefault(channel_id, []).append((start, end))
        changed = []
        for channel in Channel.objects.filter(pk__in=chunk).only("pk", "history_coverage"):
            kept = coverage.to_json(
                coverage.intersect(coverage.from_json(channel.history_coverage), periods.get(channel.pk, []))
            )
            if kept != channel.history_coverage:
                channel.history_coverage = kept
                changed.append(channel)
        Channel.objects.bulk_update(changed, ["history_coverage"])


def collect_media_files(msg_ids: Sequence[int]) -> list[tuple[object, str]]:
    """Capture ``(storage, name)`` for on-disk files owned *only* by the messages ``msg_ids``.

    Called *before* the bulk row delete so the cascade doesn't make the FileField
    descriptors unreachable. Media paths are keyed by Telegram file id
    (``photos/{telegram_id}.ext`` …, no per-message segment), so a forwarded copy
    and a kept in-target message can point at the *same* file. A path is returned
    for deletion only when no surviving (non-purged) row of the same model still
    references it — otherwise purging an out-of-target forward would delete a kept
    message's media. Pks and names are queried ``_CHUNK_SIZE`` at a time; the
    per-path purged-row counts are summed over *every* chunk before any path is
    judged, so a file referenced from several chunks is counted correctly.
    """
    if not msg_ids:
        return []
    files: list[tuple[object, str]] = []
    for model, field_name in _MEDIA_FIELDS:
        purged_counts: dict[str, int] = {}
        storages: dict[str, object] = {}
        for chunk in batched(msg_ids, _CHUNK_SIZE):
            for media in model.objects.filter(message_id__in=chunk).only("pk", field_name):
                descriptor = getattr(media, field_name)
                if descriptor and descriptor.name:
                    purged_counts[descriptor.name] = purged_counts.get(descriptor.name, 0) + 1
                    storages[descriptor.name] = descriptor.storage
        if not purged_counts:
            continue
        # Total rows (across ALL messages, purged or kept) referencing each path.
        total_counts: dict[str, int] = {}
        for names in batched(purged_counts, _CHUNK_SIZE):
            total_counts.update(
                (row[field_name], row["total"])
                for row in model.objects.filter(**{f"{field_name}__in": names})
                .values(field_name)
                .annotate(total=Count("pk"))
            )
        for name, purged_n in purged_counts.items():
            # Delete only when every row referencing this shared file is being purged.
            if total_counts.get(name, purged_n) <= purged_n:
                files.append((storages[name], name))
    return files


def _recently_modified(storage: object, name: str, grace_seconds: float) -> bool:
    """Whether the stored file ``name`` was written within ``grace_seconds`` (False when it can't be stat'ed)."""
    if grace_seconds <= 0:
        return False
    try:
        st = os.stat(storage.path(name))
    except (NotImplementedError, OSError):
        return False
    return recently_modified(st, grace_seconds)


def remove_files(
    files: list[tuple[object, str]], *, grace_seconds: float = RECENT_FILE_GRACE_SECONDS
) -> tuple[int, int, int]:
    """Delete the captured files from their storage backend; return (removed, failed, skipped).

    Runs after the row delete, and re-checks each chunk right before unlinking it:
    a file some row references by now — a crawl may have linked a new message to
    the shared path (``crawler.media_handler._existing_sibling_file``) since the
    reference count — or one modified within ``grace_seconds`` (a re-download in
    progress) is skipped.
    """
    removed = 0
    failed = 0
    skipped = 0
    for chunk in batched(files, _CHUNK_SIZE):
        still_referenced = referenced_among(name for _, name in chunk)
        for storage, name in chunk:
            if name in still_referenced or _recently_modified(storage, name, grace_seconds):
                skipped += 1
                continue
            try:
                storage.delete(name)
                removed += 1
            except OSError:
                failed += 1
    return removed, failed, skipped


def purge(*, dry_run: bool = False, grace_seconds: float = RECENT_FILE_GRACE_SECONDS) -> PurgeReport:
    """Drive the purge end-to-end. Returns a :class:`PurgeReport` for the caller.

    ``grace_seconds`` is the recent-file grace period of :func:`remove_files`.
    """
    if not marked_in_target_channels().exists():
        raise CommandError(
            "No channels are marked in-target — refusing to proceed (would delete every message). "
            "Mark at least one channel with an in-target label before running this command."
        )

    # One snapshot of the candidate pks drives the count, the media sweep and the
    # delete, each in chunks of _CHUNK_SIZE.
    msg_ids = sorted(set(find_purgeable_messages().values_list("pk", flat=True)))
    msg_count = len(msg_ids)
    files = collect_media_files(msg_ids)

    if dry_run or msg_count == 0:
        return PurgeReport(
            candidate_messages=msg_count,
            candidate_media_files=len(files),
            dry_run=dry_run,
        )

    deleted_by_type: Counter[str] = Counter()
    purged_channels: set[int] = set()
    with transaction.atomic():
        for chunk in batched(msg_ids, _CHUNK_SIZE):
            # The tag shield is re-applied: a post tagged since the snapshot keeps its messages.
            doomed = Message.objects.filter(pk__in=chunk).exclude(_tag_shield())
            purged_channels.update(doomed.values_list("channel_id", flat=True).distinct())
            _deleted, by_type = doomed.delete()
            deleted_by_type.update(by_type)
        trim_history_coverage(purged_channels)
    # Explicit labels: of the five media models only "MessageOtherMedia" contains
    # the substring "Media", so a substring match would omit the other four.
    media_labels = {
        "webapp.MessagePicture",
        "webapp.MessageVideo",
        "webapp.MessageAudio",
        "webapp.MessageSticker",
        "webapp.MessageOtherMedia",
    }
    deleted_media_rows = sum(count for label, count in deleted_by_type.items() if label in media_labels)

    removed, failed, skipped = remove_files(files, grace_seconds=grace_seconds)
    return PurgeReport(
        candidate_messages=msg_count,
        candidate_media_files=len(files),
        deleted_messages=deleted_by_type.get("webapp.Message", 0),
        deleted_media_rows=deleted_media_rows,
        removed_files=removed,
        failed_files=failed,
        skipped_files=skipped,
    )


class Command(BaseCommand):
    help = (
        "Delete messages and their on-disk media for channels outside the in-target scope. "
        "A media file is kept when a row references it again by deletion time, or when it was modified "
        f"within the last {RECENT_FILE_GRACE_SECONDS // 60} minutes (a crawl may be writing it). "
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
        if report.skipped_files:
            self.stdout.write(
                f"Left {report.skipped_files:,} media files on disk: a row references them again, or they were "
                f"modified within the last {RECENT_FILE_GRACE_SECONDS // 60} minutes "
                "(`purge_orphan_media` reclaims any that end up unreferenced)."
            )
        self.stdout.write(
            self.style.NOTICE(
                "Tip: run `VACUUM` (SQLite) or use the Maintenance section of the backoffice to reclaim DB file space."
            )
        )
