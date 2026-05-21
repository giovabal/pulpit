import asyncio
import datetime
import logging
import os
import re
import shutil
import tempfile
from argparse import ArgumentParser, BooleanOptionalAction
from collections import Counter
from collections.abc import Iterator
from contextlib import contextmanager
from time import sleep
from typing import Any

from django.conf import settings
from django.core.management.base import BaseCommand
from django.db.models import F, Q

from crawler.channel_crawler import ChannelCrawler
from crawler.client import TelegramAPIClient
from crawler.hole_fixer import fix_message_holes
from crawler.media_handler import MediaHandler
from crawler.reference_resolver import DEAD_PREFIX, SKIPPABLE_REFERENCES, ReferenceResolver
from webapp.models import (
    Channel,
    Message,
    MessageAudio,
    MessageOtherMedia,
    MessagePicture,
    MessageSticker,
    MessageVideo,
)
from webapp.utils.channel_types import VALID_CHANNEL_TYPES, channel_type_filter
from webapp.utils.id_ranges import parse_id_ranges

from telethon import errors
from telethon.sync import TelegramClient

logger = logging.getLogger(__name__)


from dataclasses import dataclass  # noqa: E402


@dataclass(frozen=True)
class CrawlOptions:
    """All crawl_channels options resolved from CLI flags and configuration/.operations-crawl.

    Built once at the top of ``handle`` so subsequent code doesn't have to keep
    repeating ``options["x"] or settings.CRAWL_X`` (which silently demotes
    explicit ``False`` to the default), and the option surface is
    self-documenting in one place.
    """

    # Channels phase
    get_channels_info: bool
    update_type_excluded_info: bool
    mine_about_texts: bool
    fetch_recommended: bool
    retry_lost_and_private: bool

    # Messages phase
    get_new_messages: bool
    fetch_replies: bool
    do_refresh: bool
    refresh_limit: int | None
    refresh_from: datetime.date | None
    refresh_to: datetime.date | None
    fix_holes: bool
    fix_missing_media: bool
    retry_lost_messages: bool
    retry_references: bool
    force_retry: bool

    # Media downloads (apply to get_new_messages, fix_holes, and fix_missing_media)
    download_images: bool
    download_video: bool
    download_audio: bool
    download_stickers: bool
    download_other_media: bool

    # Degrees phase
    in_degrees: bool
    out_degrees: bool

    # Scope
    ids_str: str | None
    channel_types: list[str]
    channel_groups: list[str]

    @property
    def need_client(self) -> bool:
        return (
            self.get_channels_info
            or self.mine_about_texts
            or self.fetch_recommended
            or self.get_new_messages
            or self.do_refresh
            or self.fix_holes
            or self.fix_missing_media
            or self.retry_lost_messages
            or self.retry_references
            or self.fetch_replies
        )


@contextmanager
def per_channel_step(
    stdout: Any,
    style: Any,
    printer: "ProgressPrinter",
    *,
    action: str,
    channel: Any,
    ensure_newline_on_success: bool = True,
) -> Iterator[None]:
    """Wrap a per-channel Telegram operation with the standard error scaffolding.

    Catches the two recurring failure modes:
      * ``FloodWaitError`` → prints a WARNING line and sleeps when
        ``settings.IGNORE_FLOODWAIT`` is false. The wrapped block is skipped.
      * any other ``Exception`` → prints a WARNING line and logs the traceback.

    On success, optionally ensures the progress-printer terminates the current
    line (matching the historical ``printer.ensure_newline()`` calls).
    """
    try:
        yield
    except errors.FloodWaitError as exc:
        printer.newline()
        stdout.write(style.WARNING(f"Flood wait {action} for {channel}: {exc}"))
        if not settings.IGNORE_FLOODWAIT:
            sleep(settings.TELEGRAM_FLOODWAIT_SLEEP_SECONDS)
    except Exception as exc:
        printer.newline()
        stdout.write(style.WARNING(f"Error {action} for {channel}: {exc}"))
        logger.exception("%s failed for %s", action, channel)
    else:
        if ensure_newline_on_success:
            printer.ensure_newline()


_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_ABOUT_REF_RE = re.compile(r"t\.me/((?:[-\w.]|(?:%[\da-fA-F]{2}))+)")


class ProgressPrinter:
    """Manages progress lines.

    In TTY mode lines are overwritten in place with carriage return.
    In non-TTY mode (file/pipe — the web output panel) each status change
    is emitted as a complete newline-terminated line so the log reader
    forwards it immediately.  High-frequency indented callbacks (e.g. per-
    message stats refresh) are throttled to one line every 100 calls.
    """

    def __init__(self, stdout: Any, total: int) -> None:
        self._stdout = stdout
        self._total = total
        self._current_channel: int | None = None
        self._line_length = 0
        self._is_tty = getattr(stdout, "isatty", lambda: False)()
        self._indented_calls = 0
        self._last_indented: tuple[str, str] | None = None

    def _fit(self, line: str) -> str:
        if not self._is_tty:
            return line
        cols = shutil.get_terminal_size().columns
        return line if len(line) <= cols else line[: cols - 1]

    def status(self, message: str, channel_index: int) -> None:
        if self._is_tty:
            if self._current_channel != channel_index:
                if self._current_channel is not None:
                    self._stdout.write("", ending="\n")
                self._current_channel = channel_index
                self._line_length = 0
            line = self._fit(f"[{channel_index}/{self._total}] {message}")
            padding = " " * max(0, self._line_length - len(line))
            self._stdout.write(f"\r{line}{padding}", ending="")
            self._stdout.flush()
            self._line_length = len(line)
        else:
            self._current_channel = channel_index
            line = f"[{channel_index}/{self._total}] {message}"
            self._stdout.write(line, ending="\n")
            self._stdout.flush()
            self._line_length = len(line)

    def indented(self, message: str, indent: str) -> None:
        if self._is_tty:
            line = self._fit(f"{indent}{message}")
            padding = " " * max(0, self._line_length - len(line))
            self._stdout.write(f"\r{line}{padding}", ending="")
            self._stdout.flush()
            self._line_length = len(line)
        else:
            self._indented_calls += 1
            self._last_indented = (message, indent)
            if self._indented_calls % 100 == 0:
                line = f"{indent}{message}"
                self._stdout.write(line, ending="\n")
                self._stdout.flush()
                self._line_length = len(line)

    def newline(self) -> None:
        if not self._is_tty and self._last_indented and self._indented_calls % 100 != 0:
            message, indent = self._last_indented
            self._stdout.write(f"{indent}{message}", ending="")
            self._stdout.flush()
        self._stdout.write("", ending="\n")
        self._line_length = 0
        self._current_channel = None
        self._indented_calls = 0
        self._last_indented = None

    def ensure_newline(self) -> None:
        """Move to a new line only if a progress line is currently shown."""
        if self._line_length > 0:
            self.newline()

    def progress(self, line: str) -> None:
        """Render an arbitrary progress line.

        TTY: overwrites the current line via carriage return (so a long
        per-iteration loop stays on a single visible row).
        Non-TTY: emits a complete newline-terminated line so the web log
        reader forwards it immediately.

        Use this instead of replicating the private ``_fit`` / ``_line_length``
        bookkeeping in callers — it keeps every progress loop consistent.
        """
        if self._is_tty:
            line = self._fit(line)
            padding = " " * max(0, self._line_length - len(line))
            self._stdout.write(f"\r{line}{padding}", ending="")
            self._stdout.flush()
            self._line_length = len(line)
        else:
            self._stdout.write(line, ending="\n")
            self._stdout.flush()
            self._line_length = len(line)

    def announce(self, message: str) -> None:
        """Emit a single newline-terminated banner line marking a new section.
        Resets the progress-line tracking so the next ``progress`` call starts fresh."""
        self._stdout.write(message, ending="\n")
        self._stdout.flush()
        self._line_length = 0


class _WarningLogHandler(logging.Handler):
    """Route WARNING+ log records to the terminal as coloured, newline-separated messages."""

    def __init__(self, printer: ProgressPrinter, style: Any) -> None:
        super().__init__(logging.WARNING)
        self._printer = printer
        self._style = style

    def emit(self, record: logging.LogRecord) -> None:
        self._printer.ensure_newline()
        msg = self.format(record)
        print(self._style.WARNING(msg) if record.levelno < logging.ERROR else self._style.ERROR(msg))


class Command(BaseCommand):
    args = ""
    help = "crawling Telegram groups"

    def add_arguments(self, parser: ArgumentParser) -> None:
        # ── Channels ──────────────────────────────────────────────────────────
        # All toggles use BooleanOptionalAction with default=None so that an
        # explicit --no-<flag> from the CLI or the Operations panel can disable
        # the operation regardless of the configuration/.operations-crawl
        # default. The settings default applies only when neither --<flag> nor
        # --no-<flag> is passed.
        parser.add_argument(
            "--get-channels-info",
            action=BooleanOptionalAction,
            default=None,
            help="Update profile pictures and full channel details for each channel in scope.",
        )
        parser.add_argument(
            "--update-type-excluded-info",
            action=BooleanOptionalAction,
            default=None,
            help=(
                "Also update metadata for in-target channels whose type is not in --channel-types. "
                "Requires --get-channels-info."
            ),
        )
        parser.add_argument(
            "--mine-about-texts",
            action=BooleanOptionalAction,
            default=None,
            help=(
                "Scan the 'about' field of all channels in the database for t.me/ links "
                "and fetch any referenced channels not yet in the database."
            ),
        )
        parser.add_argument(
            "--fetch-recommended",
            "--fetch-recommended-channels",  # backward-compat alias for the longer form
            dest="fetch_recommended",
            action=BooleanOptionalAction,
            default=None,
            help=(
                "Fetch Telegram-recommended channels for each in-target channel and add any new ones to the database."
            ),
        )
        parser.add_argument(
            "--retry-lost-and-private",
            action=BooleanOptionalAction,
            default=None,
            help=(
                "Include channels marked as lost or private in the crawl scope. "
                "Each such channel is resolved at its turn: if now accessible its flag is cleared; "
                "if still inaccessible its flag is updated and it is skipped."
            ),
        )
        # ── Messages ──────────────────────────────────────────────────────────
        parser.add_argument(
            "--get-new-messages",
            action=BooleanOptionalAction,
            default=None,
            help="Fetch new messages for each in-target channel.",
        )
        parser.add_argument(
            "--fetch-replies",
            action=BooleanOptionalAction,
            default=None,
            help=(
                "Fetch reply messages from linked discussion groups. "
                "When combined with --get-new-messages, fetches replies for newly crawled posts; "
                "when combined with --refresh-messages-stats, fetches replies for already-stored posts."
            ),
        )
        parser.add_argument(
            "--refresh-messages-stats",
            action=BooleanOptionalAction,
            default=None,
            help=(
                "Re-fetch views, forwards, pinned status, and reactions for already-stored messages. "
                "Defaults to CRAWL_REFRESH_MESSAGES_STATS; pass --no-refresh-messages-stats to disable "
                "for this run even when the configuration default is true."
            ),
        )
        parser.add_argument(
            "--refresh-limit",
            type=int,
            default=None,
            metavar="N",
            help="Limit stats refresh to the N most recent messages within the date window.",
        )
        parser.add_argument(
            "--refresh-from",
            default=None,
            metavar="YYYY-MM-DD",
            help="Only refresh messages on or after this date.",
        )
        parser.add_argument(
            "--refresh-to",
            default=None,
            metavar="YYYY-MM-DD",
            help="Only refresh messages on or before this date.",
        )
        parser.add_argument(
            "--fix-holes",
            "--fixholes",  # backward-compat alias (kebab-snake mismatch in older docs)
            dest="fix_holes",
            action=BooleanOptionalAction,
            default=None,
            help="Scan each channel's message ID sequence for gaps and fetch any missing messages.",
        )
        parser.add_argument(
            "--fix-missing-media",
            action=BooleanOptionalAction,
            default=None,
            help=(
                "Identify messages whose media file is absent from disk or was never downloaded "
                "and re-fetch it from Telegram. Honors --download-images / --download-video / "
                "--download-audio / --download-stickers / --download-other-media (and their "
                "--no- counterparts)."
            ),
        )
        parser.add_argument(
            "--download-images",
            action=BooleanOptionalAction,
            default=None,
            help=(
                "Download photo files attached to messages. Applies to --get-new-messages, "
                "--fix-holes, and --fix-missing-media. Defaults to "
                "TELEGRAM_CRAWLER_DOWNLOAD_IMAGES; pass --no-download-images to disable for "
                "this run."
            ),
        )
        parser.add_argument(
            "--download-video",
            action=BooleanOptionalAction,
            default=None,
            help=(
                "Download video files attached to messages. Applies to --get-new-messages, "
                "--fix-holes, and --fix-missing-media. Defaults to "
                "TELEGRAM_CRAWLER_DOWNLOAD_VIDEO; pass --no-download-video to disable for "
                "this run."
            ),
        )
        parser.add_argument(
            "--download-audio",
            action=BooleanOptionalAction,
            default=None,
            help=(
                "Download audio files attached to messages — both voice notes and uploaded "
                "audio documents. Applies to --get-new-messages, --fix-holes, and "
                "--fix-missing-media. Defaults to TELEGRAM_CRAWLER_DOWNLOAD_AUDIO; pass "
                "--no-download-audio to disable for this run."
            ),
        )
        parser.add_argument(
            "--download-stickers",
            action=BooleanOptionalAction,
            default=None,
            help=(
                "Download stickers attached to messages — static webp, animated TGS, and "
                "video webm stickers. Applies to --get-new-messages, --fix-holes, and "
                "--fix-missing-media. Defaults to TELEGRAM_CRAWLER_DOWNLOAD_STICKERS; pass "
                "--no-download-stickers to disable for this run."
            ),
        )
        parser.add_argument(
            "--download-other-media",
            action=BooleanOptionalAction,
            default=None,
            help=(
                "Download non-photo, non-video, non-audio, non-sticker documents (PDFs, "
                "archives, etc.). Applies to --get-new-messages, --fix-holes, and "
                "--fix-missing-media. Defaults to TELEGRAM_CRAWLER_DOWNLOAD_OTHER_MEDIA; "
                "pass --no-download-other-media to disable for this run."
            ),
        )
        parser.add_argument(
            "--retry-lost-messages",
            action=BooleanOptionalAction,
            default=None,
            help=(
                "Re-fetch every message marked is_lost=True. Messages that come back are unmarked and "
                "their stats refreshed; messages that Telegram still doesn't return stay lost."
            ),
        )
        parser.add_argument(
            "--retry-references",
            action=BooleanOptionalAction,
            default=None,
            help="Retry all pending unresolved t.me/ references found in messages.",
        )
        parser.add_argument(
            "--force-retry-unresolved-references",
            action=BooleanOptionalAction,
            default=None,
            help=(
                "When retrying references, also re-attempt those already marked as permanently "
                "unresolvable. Requires --retry-references."
            ),
        )
        # ── Degrees ───────────────────────────────────────────────────────────
        parser.add_argument(
            "--in-degrees",
            action=BooleanOptionalAction,
            default=None,
            help="Recompute in-degree and out-degree for all in-target channels.",
        )
        parser.add_argument(
            "--out-degrees",
            action=BooleanOptionalAction,
            default=None,
            help="Recompute citation degree for out-of-target channels cited by in-target ones.",
        )
        # ── Scope ─────────────────────────────────────────────────────────────
        parser.add_argument(
            "--ids",
            default=None,
            metavar="RANGES",
            help=(
                "Restrict to specific channel DB IDs. Accepts comma-separated values and ranges, "
                "e.g. '5, 10-20, 50-' (from 50 upward), '-30' (up to 30). Tokens are OR-ed."
            ),
        )
        parser.add_argument(
            "--channel-types",
            dest="channel_types",
            default=None,
            metavar="TYPES",
            help=(
                "Comma-separated list of Telegram entity types. "
                "Available: CHANNEL, GROUP, USER. Defaults to the DEFAULT_CHANNEL_TYPES setting."
            ),
        )
        parser.add_argument(
            "--channel-groups",
            dest="channel_groups",
            default=None,
            metavar="GROUPS",
            help=(
                "Comma-separated list of ChannelGroup keys. "
                "Only channels belonging to at least one of these groups are included."
            ),
        )

    def _refresh_channel_info_for_channel(
        self,
        channel: Channel,
        crawler: ChannelCrawler,
        index: int,
        printer: ProgressPrinter,
    ) -> None:
        with per_channel_step(self.stdout, self.style, printer, action="updating info", channel=channel):
            crawler.refresh_channel_info(
                channel.telegram_id,
                status_callback=lambda message, idx=index: printer.status(message, idx),
            )

    def _fix_holes_for_channel(
        self,
        channel: Channel,
        crawler: ChannelCrawler,
        index: int,
        printer: ProgressPrinter,
    ) -> None:
        try:
            telegram_channel = crawler.api_client.client.get_entity(channel.telegram_id)
        except errors.FloodWaitError as exc:
            printer.newline()
            self.stdout.write(self.style.WARNING(f"Flood wait resolving entity for {channel}: {exc}"))
            if not settings.IGNORE_FLOODWAIT:
                sleep(settings.TELEGRAM_FLOODWAIT_SLEEP_SECONDS)
            return
        except Exception as exc:
            printer.newline()
            self.stdout.write(self.style.WARNING(f"Could not resolve entity for {channel}: {exc}"))
            return
        channel_label = f"[id={channel.id}] {channel}"
        with per_channel_step(self.stdout, self.style, printer, action="fixing holes", channel=channel):
            fix_message_holes(
                channel,
                telegram_channel,
                crawler.api_client,
                crawler.get_message,
                lambda message, idx=index: printer.status(message, idx),
                channel_label,
                0,
            )

    def _fetch_replies_for_channel(
        self,
        channel: Channel,
        crawler: ChannelCrawler,
        index: int,
        printer: ProgressPrinter,
        *,
        min_telegram_id: int | None = None,
        max_telegram_id: int | None = None,
    ) -> None:
        if not channel.linked_chat_id:
            return
        with per_channel_step(self.stdout, self.style, printer, action="fetching replies", channel=channel):
            crawler.fetch_channel_replies(
                channel,
                min_telegram_id=min_telegram_id,
                max_telegram_id=max_telegram_id,
                status_callback=lambda message, idx=index: printer.status(message, idx),
            )

    def _retry_lost_for_channel(
        self,
        channel: Channel,
        crawler: ChannelCrawler,
        index: int,
        total_channels: int,
        printer: ProgressPrinter,
    ) -> None:
        if not Message.objects.filter(channel=channel, is_lost=True).exists():
            return
        try:
            telegram_channel = crawler.api_client.client.get_entity(channel.telegram_id)
        except ValueError:
            if not channel.username:
                printer.newline()
                self.stdout.write(
                    self.style.WARNING(
                        f"Skipping retry-lost for channel {channel.telegram_id}: "
                        "entity not in cache and no username stored"
                    )
                )
                return
            try:
                telegram_channel = crawler.api_client.client.get_entity(channel.username)
            except Exception as error:
                printer.newline()
                self.stdout.write(self.style.WARNING(f"Skipping retry-lost for channel {channel.telegram_id}: {error}"))
                return

        prefix = f"[{index}/{total_channels}] [id={channel.id}] {channel} | "
        try:
            crawler.retry_lost_messages(
                channel,
                telegram_channel,
                status_callback=lambda message, p=prefix: printer.indented(message, p),
            )
        except errors.FloodWaitError as error:
            printer.newline()
            self.stdout.write(
                self.style.WARNING(f"Skipping retry-lost for channel {channel.telegram_id} due to flood wait: {error}")
            )
            if not settings.IGNORE_FLOODWAIT:
                sleep(settings.TELEGRAM_FLOODWAIT_SLEEP_SECONDS)
            return
        except errors.rpcerrorlist.ChannelPrivateError:
            printer.newline()
            self.stdout.write(
                self.style.WARNING(
                    f"Skipping retry-lost for channel {channel.telegram_id}: channel is private or inaccessible"
                )
            )
            return
        except Exception as error:
            printer.newline()
            self.stdout.write(self.style.WARNING(f"Retry-lost failed for channel {channel.telegram_id}: {error}"))
            logger.exception("retry_lost_messages failed for %s", channel)
            return
        printer.newline()

    def _refresh_channel(
        self,
        channel: Channel,
        crawler: ChannelCrawler,
        index: int,
        total_channels: int,
        refresh_limit: int | None,
        refresh_from: datetime.date | None,
        refresh_to: datetime.date | None,
        pre_crawl_max_id: int,
        printer: ProgressPrinter,
    ) -> None:
        # Resolve entity: try numeric ID first (cached), fall back to username only on failure.
        try:
            telegram_channel = crawler.api_client.client.get_entity(channel.telegram_id)
        except ValueError:
            if not channel.username:
                printer.newline()
                self.stdout.write(
                    self.style.WARNING(
                        f"Skipping refresh for channel {channel.telegram_id}: entity not in cache and no username stored"
                    )
                )
                return
            try:
                telegram_channel = crawler.api_client.client.get_entity(channel.username)
            except Exception as error:
                printer.newline()
                self.stdout.write(self.style.WARNING(f"Skipping refresh for channel {channel.telegram_id}: {error}"))
                return

        refresh_prefix = f"[{index}/{total_channels}] [id={channel.id}] {channel} | "
        try:
            crawler.refresh_message_stats(
                channel,
                telegram_channel,
                limit=refresh_limit,
                min_date=refresh_from,
                max_date=refresh_to,
                max_telegram_id=pre_crawl_max_id,
                status_callback=lambda message, prefix=refresh_prefix: printer.indented(message, prefix),
            )
        except errors.FloodWaitError as error:
            printer.newline()
            self.stdout.write(
                self.style.WARNING(f"Skipping refresh for channel {channel.telegram_id} due to flood wait: {error}")
            )
            if not settings.IGNORE_FLOODWAIT:
                sleep(settings.TELEGRAM_FLOODWAIT_SLEEP_SECONDS)
            return
        except errors.rpcerrorlist.ChannelPrivateError:
            printer.newline()
            self.stdout.write(
                self.style.WARNING(
                    f"Skipping refresh for channel {channel.telegram_id}: channel is private or inaccessible"
                )
            )
            return
        except errors.ServerError as error:
            printer.newline()
            self.stdout.write(
                self.style.WARNING(
                    f"Telegram server error refreshing channel {channel.telegram_id}: {error} — retrying in 30s…"
                )
            )
            sleep(30)
            try:
                crawler.refresh_message_stats(
                    channel,
                    telegram_channel,
                    limit=refresh_limit,
                    min_date=refresh_from,
                    max_date=refresh_to,
                    max_telegram_id=pre_crawl_max_id,
                    status_callback=lambda message, prefix=refresh_prefix: printer.indented(message, prefix),
                )
            except Exception as retry_error:
                printer.newline()
                self.stdout.write(self.style.WARNING(f"Retry failed for channel {channel.telegram_id}: {retry_error}"))
                logger.exception("Refresh retry failed for channel %s", channel.telegram_id)
                return
        except Exception as error:
            printer.newline()
            self.stdout.write(self.style.WARNING(f"Skipping refresh for channel {channel.telegram_id}: {error}"))
            logger.exception("Refresh failed for channel %s", channel.telegram_id)
            return
        printer.newline()

    def _fix_missing_media(
        self,
        crawl_qs: Any,
        api_client: TelegramAPIClient,
        download_temp_dir: str,
        printer: ProgressPrinter,
        opts: CrawlOptions,
    ) -> None:
        """Re-download media files that are absent from disk or were never fetched."""
        fix_handler = MediaHandler(
            api_client,
            download_temp_dir=download_temp_dir,
            download_images=opts.download_images,
            download_video=opts.download_video,
            download_audio=opts.download_audio,
            download_stickers=opts.download_stickers,
            download_other_media=opts.download_other_media,
        )

        # Messages with each media_type but no corresponding record.
        # Each media-type bucket is only scanned when its toggle is on.
        needs_pic: set[int] = set()
        if opts.download_images:
            needs_pic = set(
                Message.objects.filter(channel__in=crawl_qs, media_type="photo")
                .filter(messagepicture__isnull=True)
                .values_list("id", flat=True)
            )
        needs_vid: set[int] = set()
        if opts.download_video:
            needs_vid = set(
                Message.objects.filter(channel__in=crawl_qs, media_type="video")
                .filter(messagevideo__isnull=True)
                .values_list("id", flat=True)
            )
        needs_aud: set[int] = set()
        if opts.download_audio:
            needs_aud = set(
                Message.objects.filter(channel__in=crawl_qs, media_type="audio")
                .filter(messageaudio__isnull=True)
                .values_list("id", flat=True)
            )
        needs_sticker: set[int] = set()
        if opts.download_stickers:
            needs_sticker = set(
                Message.objects.filter(channel__in=crawl_qs, media_type="sticker")
                .filter(messagesticker__isnull=True)
                .values_list("id", flat=True)
            )
        needs_other: set[int] = set()
        if opts.download_other_media:
            needs_other = set(
                Message.objects.filter(channel__in=crawl_qs, media_type="document")
                .filter(messageothermedia__isnull=True)
                .values_list("id", flat=True)
            )

        # Records that exist but whose file is missing on disk
        if opts.download_images:
            for mp in MessagePicture.objects.filter(message__channel__in=crawl_qs).select_related("message"):
                if mp.picture and not os.path.exists(mp.picture.path):
                    needs_pic.add(mp.message_id)
        if opts.download_video:
            for mv in MessageVideo.objects.filter(message__channel__in=crawl_qs).select_related("message"):
                if mv.video and not os.path.exists(mv.video.path):
                    needs_vid.add(mv.message_id)
        if opts.download_audio:
            for ma in MessageAudio.objects.filter(message__channel__in=crawl_qs).select_related("message"):
                if ma.audio and not os.path.exists(ma.audio.path):
                    needs_aud.add(ma.message_id)
        if opts.download_stickers:
            for ms in MessageSticker.objects.filter(message__channel__in=crawl_qs).select_related("message"):
                if ms.sticker and not os.path.exists(ms.sticker.path):
                    needs_sticker.add(ms.message_id)
        if opts.download_other_media:
            for mo in MessageOtherMedia.objects.filter(message__channel__in=crawl_qs).select_related("message"):
                if mo.media_file and not os.path.exists(mo.media_file.path):
                    needs_other.add(mo.message_id)

        all_msg_pks = needs_pic | needs_vid | needs_aud | needs_sticker | needs_other
        if not all_msg_pks:
            self.stdout.write("\nNo missing media found.")
            return

        # Group by channel: channel_pk → [(message_pk, telegram_id)]
        channel_to_msgs: dict[int, list[tuple[int, int]]] = {}
        for msg_pk, channel_pk, telegram_id in Message.objects.filter(pk__in=all_msg_pks).values_list(
            "id", "channel_id", "telegram_id"
        ):
            channel_to_msgs.setdefault(channel_pk, []).append((msg_pk, telegram_id))

        n_channels = len(channel_to_msgs)
        n_messages = len(all_msg_pks)
        self.stdout.write(f"\nFixing missing media: {n_messages} message(s) across {n_channels} channel(s)")

        downloaded = 0
        skipped = 0
        _BATCH = 100
        for ch_idx, (channel_pk, msg_list) in enumerate(channel_to_msgs.items(), start=1):
            channel = Channel.objects.get(pk=channel_pk)
            channel_label = f"[id={channel.id}] {channel}"
            telegram_ids = [tid for _, tid in msg_list]
            pk_by_tid: dict[int, int] = {tid: pk for pk, tid in msg_list}
            n = len(telegram_ids)
            printer.status(f"{channel_label} | {n} message(s) with missing media", ch_idx)
            try:
                api_client.wait()
                telegram_entity = api_client.client.get_entity(channel.telegram_id)
            except errors.FloodWaitError as exc:
                printer.newline()
                self.stdout.write(self.style.WARNING(f"Flood wait for {channel}: {exc}"))
                skipped += n
                if not settings.IGNORE_FLOODWAIT:
                    sleep(settings.TELEGRAM_FLOODWAIT_SLEEP_SECONDS)
                continue
            except Exception as exc:
                printer.newline()
                self.stdout.write(self.style.WARNING(f"Could not get entity for {channel}: {exc}"))
                skipped += n
                continue

            for i in range(0, n, _BATCH):
                batch_tids = telegram_ids[i : i + _BATCH]
                try:
                    api_client.wait()
                    tg_messages = api_client.client.get_messages(telegram_entity, ids=batch_tids)
                except errors.FloodWaitError as exc:
                    printer.newline()
                    self.stdout.write(self.style.WARNING(f"Flood wait fetching messages for {channel}: {exc}"))
                    skipped += len(batch_tids)
                    if not settings.IGNORE_FLOODWAIT:
                        sleep(settings.TELEGRAM_FLOODWAIT_SLEEP_SECONDS)
                    continue
                except Exception as exc:
                    printer.newline()
                    self.stdout.write(self.style.WARNING(f"Error fetching messages for {channel}: {exc}"))
                    skipped += len(batch_tids)
                    continue

                if not isinstance(tg_messages, list):
                    tg_messages = [tg_messages]

                for tg_msg in tg_messages:
                    if tg_msg is None or not hasattr(tg_msg, "peer_id"):
                        skipped += 1
                        continue
                    msg_pk = pk_by_tid.get(tg_msg.id)
                    if msg_pk in needs_pic:
                        fix_handler.download_message_picture(tg_msg)
                    if msg_pk in needs_vid:
                        fix_handler.download_message_video(tg_msg)
                    if msg_pk in needs_aud:
                        fix_handler.download_message_audio(tg_msg)
                    if msg_pk in needs_sticker:
                        fix_handler.download_message_sticker(tg_msg)
                    if msg_pk in needs_other:
                        fix_handler.download_message_other_media(tg_msg)
                    downloaded += 1
                    printer.status(
                        f"{channel_label} | downloaded {downloaded}/{n_messages}",
                        ch_idx,
                    )

            printer.ensure_newline()

        self.stdout.write(f"Missing media: {downloaded} downloaded, {skipped} skipped.")

    def _resolve_options(self, options: dict[str, Any]) -> CrawlOptions:
        from django.core.management.base import CommandError

        def _parse_date(raw: str | None, flag: str) -> datetime.date | None:
            if raw is None:
                return None
            if not _DATE_RE.match(raw):
                raise CommandError(f"{flag}: expected YYYY-MM-DD, got {raw!r}")
            return datetime.date.fromisoformat(raw)

        channel_types_raw = options["channel_types"]
        channel_types = (
            [s.strip().upper() for s in channel_types_raw.split(",") if s.strip()]
            if channel_types_raw is not None
            else list(settings.DEFAULT_CHANNEL_TYPES)
        )
        invalid_channel_types = [t for t in channel_types if t not in VALID_CHANNEL_TYPES]
        if invalid_channel_types:
            raise CommandError(
                f"Invalid --channel-types value(s): {invalid_channel_types!r}. Choose from {sorted(VALID_CHANNEL_TYPES)}."
            )
        channel_groups_raw = options.get("channel_groups")
        channel_groups = [s.strip() for s in channel_groups_raw.split(",") if s.strip()] if channel_groups_raw else []

        # Every toggle uses BooleanOptionalAction (default=None): an explicit
        # --<flag> / --no-<flag> wins over the configuration/.operations-crawl
        # default. The Operations panel emits both forms (checked → --<flag>,
        # unchecked → --no-<flag>), so an unchecked checkbox always disables
        # the operation even when the saved default is True. When neither form
        # is passed (bare CLI invocation), the settings default takes over.
        def _resolve_optional_bool(option_value: bool | None, settings_value: bool) -> bool:
            return option_value if option_value is not None else settings_value

        return CrawlOptions(
            get_channels_info=_resolve_optional_bool(options["get_channels_info"], settings.CRAWL_GET_CHANNELS_INFO),
            update_type_excluded_info=_resolve_optional_bool(
                options["update_type_excluded_info"], settings.CRAWL_UPDATE_TYPE_EXCLUDED_INFO
            ),
            mine_about_texts=_resolve_optional_bool(options["mine_about_texts"], settings.CRAWL_MINE_ABOUT_TEXTS),
            fetch_recommended=_resolve_optional_bool(options["fetch_recommended"], settings.CRAWL_FETCH_RECOMMENDED),
            retry_lost_and_private=_resolve_optional_bool(
                options["retry_lost_and_private"], settings.CRAWL_RETRY_LOST_AND_PRIVATE
            ),
            get_new_messages=_resolve_optional_bool(options["get_new_messages"], settings.CRAWL_GET_NEW_MESSAGES),
            fetch_replies=_resolve_optional_bool(options["fetch_replies"], settings.CRAWL_FETCH_REPLIES),
            do_refresh=_resolve_optional_bool(options["refresh_messages_stats"], settings.CRAWL_REFRESH_MESSAGES_STATS),
            refresh_limit=options["refresh_limit"],
            refresh_from=_parse_date(options.get("refresh_from"), "--refresh-from"),
            refresh_to=_parse_date(options.get("refresh_to"), "--refresh-to"),
            fix_holes=_resolve_optional_bool(options["fix_holes"], settings.CRAWL_FIX_HOLES),
            fix_missing_media=_resolve_optional_bool(options["fix_missing_media"], settings.CRAWL_FIX_MISSING_MEDIA),
            retry_lost_messages=_resolve_optional_bool(
                options["retry_lost_messages"], settings.CRAWL_RETRY_LOST_MESSAGES
            ),
            retry_references=_resolve_optional_bool(options["retry_references"], settings.CRAWL_RETRY_REFERENCES),
            force_retry=_resolve_optional_bool(
                options["force_retry_unresolved_references"], settings.CRAWL_FORCE_RETRY_UNRESOLVED_REFERENCES
            ),
            download_images=_resolve_optional_bool(
                options["download_images"], settings.TELEGRAM_CRAWLER_DOWNLOAD_IMAGES
            ),
            download_video=_resolve_optional_bool(options["download_video"], settings.TELEGRAM_CRAWLER_DOWNLOAD_VIDEO),
            download_audio=_resolve_optional_bool(options["download_audio"], settings.TELEGRAM_CRAWLER_DOWNLOAD_AUDIO),
            download_stickers=_resolve_optional_bool(
                options["download_stickers"], settings.TELEGRAM_CRAWLER_DOWNLOAD_STICKERS
            ),
            download_other_media=_resolve_optional_bool(
                options["download_other_media"], settings.TELEGRAM_CRAWLER_DOWNLOAD_OTHER_MEDIA
            ),
            in_degrees=_resolve_optional_bool(options["in_degrees"], settings.CRAWL_IN_DEGREES),
            out_degrees=_resolve_optional_bool(options["out_degrees"], settings.CRAWL_OUT_DEGREES),
            ids_str=options["ids"],
            channel_types=channel_types,
            channel_groups=channel_groups,
        )

    def _build_crawl_qs(self, opts: CrawlOptions) -> Any:
        """Channels included in this crawl: in-target channels and to_inspect candidates."""
        qs = Channel.objects.filter(Q(organization__is_in_target=True) | Q(to_inspect=True)).filter(
            channel_type_filter(opts.channel_types)
        )
        if not opts.retry_lost_and_private:
            qs = qs.exclude(is_lost=True).exclude(is_private=True)
        if opts.channel_groups:
            qs = qs.filter(groups__key__in=opts.channel_groups).distinct()
        return qs

    @contextmanager
    def _connect_telegram(self) -> Iterator[Any]:
        """Open a Telethon ``TelegramClient`` configured from settings, then close it."""
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)

        # Telethon's internal auto-reconnect spawns fresh Connection._send_loop /
        # _recv_loop tasks and abandons the old ones. The abandoned tasks are
        # logically replaced but stay pending until GC collects them — at which
        # point asyncio invokes the loop's exception handler with "Task was
        # destroyed but it is pending!". The warnings are pure noise (the tasks
        # were superseded on purpose) but they interrupt the crawl progress log,
        # so suppress that one message and forward everything else to the default
        # handler.
        def _suppress_destroyed_pending(loop_arg: asyncio.AbstractEventLoop, context: dict[str, Any]) -> None:
            if "was destroyed but it is pending" in context.get("message", ""):
                return
            loop_arg.default_exception_handler(context)

        loop.set_exception_handler(_suppress_destroyed_pending)

        try:
            self.stdout.write("Connecting to Telegram…", ending="")
            self.stdout.flush()
            with TelegramClient(
                settings.TELEGRAM_SESSION_NAME,
                settings.TELEGRAM_API_ID,
                settings.TELEGRAM_API_HASH,
                connection_retries=settings.TELEGRAM_CONNECTION_RETRIES,
                retry_delay=settings.TELEGRAM_RETRY_DELAY,
                flood_sleep_threshold=settings.TELEGRAM_FLOOD_SLEEP_THRESHOLD,
            ).start(phone=settings.TELEGRAM_PHONE_NUMBER) as client:
                self.stdout.write(" done")
                yield client
        finally:
            # Cancel any tasks still pending after disconnect — typically the
            # leftover send/recv loops from the last reconnect — and let them
            # finish unwinding before closing the loop. Without this drain,
            # those tasks would be GC'd later, sometimes mid-print, and emit
            # "Exception ignored in: <coroutine ...>" tracebacks on stderr.
            pending = [t for t in asyncio.all_tasks(loop) if not t.done()]
            for task in pending:
                task.cancel()
            if pending:
                try:
                    loop.run_until_complete(asyncio.gather(*pending, return_exceptions=True))
                except Exception:
                    pass
            loop.close()
            asyncio.set_event_loop(None)

    def handle(self, *args: Any, **options: Any) -> None:
        from django.core.management.base import CommandError

        # The home-page ecosystem summary is cached for an hour; drop it now so
        # newly crawled data shows up on the next page hit rather than waiting
        # for the TTL to expire.
        from webapp.cache import invalidate_home_summary_cache

        invalidate_home_summary_cache()

        opts = self._resolve_options(options)
        crawl_qs = self._build_crawl_qs(opts)

        # Locals kept for backward-compatibility with the rest of the (still-inlined)
        # crawl pipeline. Once that is split into per-phase helpers these can go.
        get_channels_info = opts.get_channels_info
        mine_about_texts = opts.mine_about_texts
        fetch_recommended = opts.fetch_recommended
        get_new_messages = opts.get_new_messages
        fetch_replies = opts.fetch_replies
        do_refresh = opts.do_refresh
        refresh_limit = opts.refresh_limit
        refresh_from = opts.refresh_from
        refresh_to = opts.refresh_to
        fix_holes = opts.fix_holes
        fix_missing_media = opts.fix_missing_media
        retry_lost_messages = opts.retry_lost_messages
        retry_references = opts.retry_references
        force_retry = opts.force_retry
        in_degrees = opts.in_degrees
        out_degrees = opts.out_degrees
        ids_str = opts.ids_str
        channel_types = opts.channel_types
        channel_groups = opts.channel_groups

        temp_root = settings.BASE_DIR / "tmp"
        temp_root.mkdir(exist_ok=True)
        download_temp_dir = tempfile.mkdtemp(prefix="crawl_channels_", dir=temp_root)

        warning_handler: _WarningLogHandler | None = None
        try:
            if opts.need_client:
                with self._connect_telegram() as client:
                    api_client = TelegramAPIClient(client)
                    media_handler = MediaHandler(
                        api_client,
                        download_temp_dir=download_temp_dir,
                        download_images=opts.download_images,
                        download_video=opts.download_video,
                        download_audio=opts.download_audio,
                        download_stickers=opts.download_stickers,
                        download_other_media=opts.download_other_media,
                    )
                    reference_resolver = ReferenceResolver(api_client)
                    crawler = ChannelCrawler(api_client, media_handler, reference_resolver)

                    channels = crawl_qs.order_by("-id")
                    if ids_str:
                        try:
                            channels = channels.filter(parse_id_ranges(ids_str))
                        except ValueError as exc:
                            raise CommandError(f"Invalid --ids value: {exc}") from exc
                    total_channels = channels.count()
                    printer = ProgressPrinter(self.stdout, total_channels)
                    warning_handler = _WarningLogHandler(printer, self.style)
                    logging.getLogger().addHandler(warning_handler)

                    # ── CHANNELS LOOP ──────────────────────────────────────────
                    if get_channels_info or mine_about_texts or fetch_recommended:
                        if get_channels_info:
                            for index, channel in enumerate(channels.iterator(chunk_size=10), start=1):
                                self._refresh_channel_info_for_channel(channel, crawler, index, printer)
                            printer.newline()

                        if get_channels_info and opts.update_type_excluded_info:
                            all_in_target_base = (
                                Channel.objects.filter(organization__is_in_target=True)
                                .exclude(is_lost=True)
                                .exclude(is_private=True)
                            )
                            excluded_by_type = all_in_target_base.exclude(channel_type_filter(channel_types)).order_by(
                                "-id"
                            )
                            if channel_groups:
                                excluded_by_type = excluded_by_type.filter(groups__key__in=channel_groups).distinct()
                            if ids_str:
                                excluded_by_type = excluded_by_type.filter(parse_id_ranges(ids_str))
                            n_excluded = excluded_by_type.count()
                            if n_excluded:
                                printer.announce(f"\nUpdating metadata for {n_excluded} type-excluded channel(s)")
                                for i, meta_ch in enumerate(excluded_by_type.iterator(chunk_size=10), start=1):
                                    printer.progress(f"Metadata [{i}/{n_excluded}] {meta_ch}")
                                    try:
                                        ch_obj, tg_ch, status = crawler.resolve_channel_or_classify(meta_ch.telegram_id)
                                    except errors.FloodWaitError as flood_err:
                                        self.stdout.write("", ending="\n")
                                        self.stdout.write(self.style.WARNING(f"Flood wait for {meta_ch}: {flood_err}"))
                                        if not settings.IGNORE_FLOODWAIT:
                                            sleep(settings.TELEGRAM_FLOODWAIT_SLEEP_SECONDS)
                                        continue
                                    except Exception as resolve_err:
                                        logger.warning("Could not resolve entity for %s: %s", meta_ch, resolve_err)
                                        continue
                                    if status == "private":
                                        Channel.objects.filter(pk=meta_ch.pk).update(is_private=True, is_lost=False)
                                        continue
                                    if status == "lost":
                                        Channel.objects.filter(pk=meta_ch.pk).update(is_lost=True, is_private=False)
                                        continue
                                    if status == "user_account":
                                        Channel.objects.filter(pk=meta_ch.pk).update(
                                            is_user_account=True, is_lost=False
                                        )
                                        continue
                                    crawler.media_handler.download_profile_picture(tg_ch)
                                    try:
                                        crawler.set_more_channel_details(ch_obj, tg_ch)
                                    except Exception as detail_err:
                                        logger.warning("Could not fetch full details for %s: %s", meta_ch, detail_err)
                                self.stdout.write("", ending="\n")

                        if mine_about_texts:
                            about_refs: set[str] = set()
                            for about_text in channels.exclude(about="").values_list("about", flat=True):
                                for m in _ABOUT_REF_RE.finditer(about_text):
                                    ref = m.group(1).strip().lower()
                                    if ref and ref not in SKIPPABLE_REFERENCES:
                                        about_refs.add(ref)
                            if about_refs:
                                known_lower = {
                                    u.lower()
                                    for u in Channel.objects.exclude(username="").values_list("username", flat=True)
                                }
                                new_about_refs = sorted(about_refs - known_lower)
                                if new_about_refs:
                                    n_about = len(new_about_refs)
                                    printer.announce(f"\nFetching {n_about} channels referenced in about texts")
                                    fetched_about = 0
                                    for i, ref in enumerate(new_about_refs, start=1):
                                        printer.progress(f"About texts [{i}/{n_about}] {ref}")
                                        try:
                                            ch_ref, _ = crawler.get_basic_channel(ref)
                                            if ch_ref:
                                                fetched_about += 1
                                        except errors.FloodWaitError as exc:
                                            self.stdout.write("", ending="\n")
                                            self.stdout.write(
                                                self.style.WARNING(f"Flood wait while fetching about references: {exc}")
                                            )
                                            if not settings.IGNORE_FLOODWAIT:
                                                sleep(settings.TELEGRAM_FLOODWAIT_SLEEP_SECONDS)
                                            break
                                        except ValueError:
                                            pass
                                        except Exception as exc:
                                            logger.warning("Error fetching about reference %s: %s", ref, exc)
                                    self.stdout.write("", ending="\n")
                                    self.stdout.write(f"About texts: {fetched_about}/{n_about} new channels fetched.")
                                else:
                                    self.stdout.write("\nAbout texts: all referenced channels already in DB.")

                        if fetch_recommended:
                            # GetChannelRecommendationsRequest only works on broadcast channels.
                            in_target_channels = [
                                ch for ch in channels if not (ch.is_user_account or ch.megagroup or ch.gigagroup)
                            ]
                            n_rec = len(in_target_channels)
                            printer.announce(f"\nFetching recommended channels for {n_rec} in-target channels")
                            rec_total = 0
                            rec_new = 0
                            for i, ch_rec in enumerate(in_target_channels, start=1):
                                printer.progress(f"Recommended channels [{i}/{n_rec}] {ch_rec}")
                                try:
                                    found, new = crawler.get_recommended_channels(ch_rec)
                                    rec_total += found
                                    rec_new += new
                                except errors.FloodWaitError as exc:
                                    self.stdout.write("", ending="\n")
                                    self.stdout.write(
                                        self.style.WARNING(f"Flood wait while fetching recommended channels: {exc}")
                                    )
                                    if not settings.IGNORE_FLOODWAIT:
                                        sleep(settings.TELEGRAM_FLOODWAIT_SLEEP_SECONDS)
                                    break
                                except Exception as exc:
                                    logger.warning("Error fetching recommended channels for %s: %s", ch_rec, exc)
                            self.stdout.write("", ending="\n")
                            self.stdout.write(f"Recommended channels: {rec_total} found, {rec_new} new.")

                    # ── MESSAGES LOOP ──────────────────────────────────────────
                    if (
                        get_new_messages
                        or do_refresh
                        or fix_holes
                        or fix_missing_media
                        or retry_lost_messages
                        or retry_references
                        or fetch_replies
                    ):
                        for index, channel in enumerate(channels.iterator(chunk_size=10), start=1):
                            pre_crawl_max_id = 0

                            if get_new_messages:
                                try:
                                    pre_crawl_max_id = crawler.get_channel(
                                        channel.telegram_id,
                                        fix_holes=fix_holes,
                                        update_info=False,
                                        status_callback=lambda message, idx=index: printer.status(message, idx),
                                    )
                                except errors.FloodWaitError as error:
                                    printer.newline()
                                    self.stdout.write(
                                        self.style.WARNING(
                                            f"Skipping channel {channel.telegram_id} due to flood wait: {error}"
                                        )
                                    )
                                    if not settings.IGNORE_FLOODWAIT:
                                        sleep(settings.TELEGRAM_FLOODWAIT_SLEEP_SECONDS)
                                    continue
                                finally:
                                    crawler._resolve_pending_forwards(
                                        lambda message, idx=index: printer.status(message, idx)
                                    )
                                printer.ensure_newline()
                                if fetch_replies:
                                    new_min = pre_crawl_max_id + 1 if pre_crawl_max_id > 0 else None
                                    self._fetch_replies_for_channel(
                                        channel, crawler, index, printer, min_telegram_id=new_min
                                    )
                            elif fix_holes:
                                self._fix_holes_for_channel(channel, crawler, index, printer)

                            if do_refresh:
                                self._refresh_channel(
                                    channel,
                                    crawler,
                                    index,
                                    total_channels,
                                    refresh_limit,
                                    refresh_from,
                                    refresh_to,
                                    pre_crawl_max_id,
                                    printer,
                                )
                                if fetch_replies:
                                    self._fetch_replies_for_channel(
                                        channel, crawler, index, printer, max_telegram_id=pre_crawl_max_id
                                    )

                            if retry_lost_messages:
                                self._retry_lost_for_channel(channel, crawler, index, total_channels, printer)

                        printer.newline()

                        if retry_references:
                            if force_retry:
                                n_missing = Message.objects.exclude(missing_references="").count()
                            else:
                                n_missing = Message.objects.filter(
                                    missing_references__regex=r"(^|[|])[^" + DEAD_PREFIX + r"]"
                                ).count()
                            if n_missing == 0:
                                self.stdout.write("\nNo unresolved message references to retry.")
                            else:
                                _ref_len = [0]

                                def _ref_progress(progress: str) -> None:
                                    line = printer._fit(f"Retrying unresolved message references [{progress}]")
                                    if printer._is_tty:
                                        padding = " " * max(0, _ref_len[0] - len(line))
                                        self.stdout.write(f"\r{line}{padding}", ending="")
                                        self.stdout.flush()
                                        _ref_len[0] = len(line)
                                    else:
                                        done_str, _, total_str = progress.partition("/")
                                        if done_str == total_str or int(done_str) % 100 == 0:
                                            self.stdout.write(line, ending="\n")
                                            self.stdout.flush()

                                self.stdout.write(f"\nRetrying {n_missing} unresolved message references", ending="")
                                self.stdout.flush()
                                crawler.get_missing_references(
                                    status_callback=_ref_progress, force_retry=force_retry, channel_qs=channels
                                )
                                self.stdout.write("", ending="\n")

                        if fix_missing_media:
                            self._fix_missing_media(channels, api_client, download_temp_dir, printer, opts)

                    media_handler.clean_leftovers()
                # The TelegramClient context manager has now exited and the connection is closed.
        finally:
            if warning_handler is not None:
                logging.getLogger().removeHandler(warning_handler)
            shutil.rmtree(download_temp_dir, ignore_errors=True)

        # ── DEGREES (no Telegram client needed) ───────────────────────────────
        if in_degrees or out_degrees:
            self.stdout.write("\nRefreshing degrees: querying message data…")
            self.stdout.flush()
            in_target_pks = set(crawl_qs.filter(organization__is_in_target=True).values_list("pk", flat=True))

            cited_pks = (
                set(
                    Message.objects.filter(
                        channel__organization__is_in_target=True,
                        forwarded_from__isnull=False,
                    ).values_list("forwarded_from_id", flat=True)
                )
                | set(
                    Message.references.through.objects.filter(
                        message__channel__organization__is_in_target=True,
                    ).values_list("channel_id", flat=True)
                )
            ) - in_target_pks

            if in_degrees and in_target_pks:
                self.stdout.write("Refreshing degrees: computing citation counts…")
                self.stdout.flush()
                fwd_cited_by = set(
                    Message.objects.filter(
                        channel__organization__is_in_target=True,
                        forwarded_from_id__in=in_target_pks,
                    )
                    .exclude(channel_id=F("forwarded_from_id"))
                    .values_list("id", "forwarded_from_id")
                )
                ref_cited_by = set(
                    Message.references.through.objects.filter(
                        message__channel__organization__is_in_target=True,
                        channel_id__in=in_target_pks,
                    )
                    .exclude(message__channel_id=F("channel_id"))
                    .values_list("message_id", "channel_id")
                )
                cited_by_counts: Counter[int] = Counter(tgt for _, tgt in fwd_cited_by | ref_cited_by)

                fwd_cites = set(
                    Message.objects.filter(
                        channel_id__in=in_target_pks,
                        forwarded_from_id__in=in_target_pks,
                    )
                    .exclude(channel_id=F("forwarded_from_id"))
                    .values_list("channel_id", "id")
                )
                ref_cites = set(
                    Message.references.through.objects.filter(
                        message__channel_id__in=in_target_pks,
                        channel_id__in=in_target_pks,
                    )
                    .exclude(message__channel_id=F("channel_id"))
                    .values_list("message__channel_id", "message_id")
                )
                cites_counts: Counter[int] = Counter(src for src, _ in fwd_cites | ref_cites)

                channels_to_update = list(Channel.objects.filter(pk__in=in_target_pks))
                for ch in channels_to_update:
                    cited_by = cited_by_counts.get(ch.pk, 0)
                    cites = cites_counts.get(ch.pk, 0)
                    if settings.REVERSED_EDGES:
                        ch.in_degree, ch.out_degree = cited_by, cites
                    else:
                        ch.in_degree, ch.out_degree = cites, cited_by

                total = len(channels_to_update)
                _deg_printer = ProgressPrinter(self.stdout, total)
                _deg_printer.announce(f"\nRefreshing degrees for {total} in-target channels")
                for i in range(0, total, 100):
                    Channel.objects.bulk_update(channels_to_update[i : i + 100], ["in_degree", "out_degree"])
                    done = min(i + 100, total)
                    _deg_printer.progress(f"Refreshing degrees for {total} in-target channels [{done}/{total}]")
                _deg_printer.ensure_newline()

            if out_degrees and cited_pks:
                fwd_cited = set(
                    Message.objects.filter(
                        channel__organization__is_in_target=True,
                        forwarded_from_id__in=cited_pks,
                    )
                    .exclude(channel_id=F("forwarded_from_id"))
                    .values_list("id", "forwarded_from_id")
                )
                ref_cited = set(
                    Message.references.through.objects.filter(
                        message__channel__organization__is_in_target=True,
                        channel_id__in=cited_pks,
                    )
                    .exclude(message__channel_id=F("channel_id"))
                    .values_list("message_id", "channel_id")
                )
                citations_counts: Counter[int] = Counter(tgt for _, tgt in fwd_cited | ref_cited)

                cited_channels = list(Channel.objects.filter(pk__in=cited_pks))
                for ch in cited_channels:
                    citations = citations_counts.get(ch.pk, 0)
                    if settings.REVERSED_EDGES:
                        ch.in_degree, ch.out_degree = citations, 0
                    else:
                        ch.in_degree, ch.out_degree = 0, citations

                total = len(cited_channels)
                _deg_printer2 = ProgressPrinter(self.stdout, total)
                for i in range(0, total, 100):
                    Channel.objects.bulk_update(cited_channels[i : i + 100], ["in_degree", "out_degree"])
                    done = min(i + 100, total)
                    _deg_printer2.progress(
                        f"Refreshing citation degree for {total} referenced channels [{done}/{total}]"
                    )
                _deg_printer2.ensure_newline()

        self.stdout.write(self.style.SUCCESS("\nCrawl complete."))
