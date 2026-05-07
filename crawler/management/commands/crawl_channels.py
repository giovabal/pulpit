import datetime
import logging
import os
import re
import shutil
import tempfile
from argparse import ArgumentParser
from collections import Counter
from time import sleep
from typing import Any

from django.conf import settings
from django.core.management.base import BaseCommand
from django.db.models import F

from crawler.channel_crawler import ChannelCrawler
from crawler.client import TelegramAPIClient
from crawler.hole_fixer import fix_message_holes
from crawler.media_handler import MediaHandler
from crawler.reference_resolver import DEAD_PREFIX, SKIPPABLE_REFERENCES, ReferenceResolver
from webapp.models import Channel, Message, MessagePicture, MessageVideo
from webapp.utils.channel_types import VALID_CHANNEL_TYPES, channel_type_filter
from webapp.utils.id_ranges import parse_id_ranges

from telethon import errors
from telethon.sync import TelegramClient

logger = logging.getLogger(__name__)

_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_ABOUT_REF_RE = re.compile(r"t\.me/((?:[-\w.]|(?:%[\da-fA-F]{2}))+)")


class ProgressPrinter:
    """Manages overwriting progress lines in the terminal via carriage return."""

    def __init__(self, stdout: Any, total: int) -> None:
        self._stdout = stdout
        self._total = total
        self._current_channel: int | None = None
        self._line_length = 0
        self._is_tty = getattr(stdout, "isatty", lambda: False)()

    def _fit(self, line: str) -> str:
        if not self._is_tty:
            return line
        cols = shutil.get_terminal_size().columns
        return line if len(line) <= cols else line[: cols - 1]

    def status(self, message: str, channel_index: int) -> None:
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

    def indented(self, message: str, indent: str) -> None:
        line = self._fit(f"{indent}{message}")
        padding = " " * max(0, self._line_length - len(line))
        self._stdout.write(f"\r{line}{padding}", ending="")
        self._stdout.flush()
        self._line_length = len(line)

    def newline(self) -> None:
        self._stdout.write("", ending="\n")
        self._line_length = 0
        self._current_channel = None

    def ensure_newline(self) -> None:
        """Move to a new line only if a progress line is currently shown."""
        if self._line_length > 0:
            self.newline()


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
        parser.add_argument(
            "--get-channels-info",
            action="store_true",
            default=False,
            help="Update profile pictures and full channel details for each channel in scope.",
        )
        parser.add_argument(
            "--mine-about-texts",
            action="store_true",
            default=False,
            help=(
                "Scan the 'about' field of all channels in the database for t.me/ links "
                "and fetch any referenced channels not yet in the database."
            ),
        )
        parser.add_argument(
            "--fetch-recommended-channels",
            action="store_true",
            default=False,
            help=(
                "Fetch Telegram-recommended channels for each interesting channel and add any new ones to the database."
            ),
        )
        parser.add_argument(
            "--retry-lost-and-private",
            action="store_true",
            default=False,
            help=(
                "Include channels marked as lost or private in the crawl scope. "
                "Each such channel is resolved at its turn: if now accessible its flag is cleared; "
                "if still inaccessible its flag is updated and it is skipped."
            ),
        )
        # ── Messages ──────────────────────────────────────────────────────────
        parser.add_argument(
            "--get-new-messages",
            action="store_true",
            default=False,
            help="Fetch new messages for each interesting channel.",
        )
        parser.add_argument(
            "--fetch-replies",
            action="store_true",
            default=False,
            help=(
                "Fetch reply messages from linked discussion groups. "
                "When combined with --get-new-messages, fetches replies for newly crawled posts; "
                "when combined with --refresh-messages-stats, fetches replies for already-stored posts."
            ),
        )
        parser.add_argument(
            "--refresh-messages-stats",
            action="store_true",
            default=False,
            help="Re-fetch views, forwards, pinned status, and reactions for already-stored messages.",
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
            "--fixholes",
            action="store_true",
            default=False,
            help="Scan each channel's message ID sequence for gaps and fetch any missing messages.",
        )
        parser.add_argument(
            "--fix-missing-media",
            action="store_true",
            default=False,
            help=(
                "Identify messages whose media file is absent from disk or was never downloaded "
                "and re-fetch it from Telegram."
            ),
        )
        parser.add_argument(
            "--retry-references",
            action="store_true",
            default=False,
            help="Retry all pending unresolved t.me/ references found in messages.",
        )
        parser.add_argument(
            "--force-retry-unresolved-references",
            action="store_true",
            default=False,
            help=(
                "When retrying references, also re-attempt those already marked as permanently "
                "unresolvable. Requires --retry-references."
            ),
        )
        # ── Degrees ───────────────────────────────────────────────────────────
        parser.add_argument(
            "--in-degrees",
            action="store_true",
            default=False,
            help="Recompute in-degree and out-degree for all interesting channels.",
        )
        parser.add_argument(
            "--out-degrees",
            action="store_true",
            default=False,
            help="Recompute citation degree for non-interesting channels cited by interesting ones.",
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
                "Comma-separated list of ChannelGroup names. "
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
        try:
            crawler.refresh_channel_info(
                channel.telegram_id,
                status_callback=lambda message, idx=index: printer.status(message, idx),
            )
            printer.ensure_newline()
        except errors.FloodWaitError as exc:
            printer.newline()
            self.stdout.write(self.style.WARNING(f"Flood wait updating info for {channel}: {exc}"))
            if not settings.IGNORE_FLOODWAIT:
                sleep(settings.TELEGRAM_FLOODWAIT_SLEEP_SECONDS)
        except Exception as exc:
            printer.newline()
            self.stdout.write(self.style.WARNING(f"Error updating info for {channel}: {exc}"))
            logger.exception("refresh_channel_info failed for %s", channel)

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
        try:
            fix_message_holes(
                channel,
                telegram_channel,
                crawler.api_client,
                crawler.get_message,
                None,
                lambda message, idx=index: printer.status(message, idx),
                channel_label,
                0,
            )
            printer.ensure_newline()
        except errors.FloodWaitError as exc:
            printer.newline()
            self.stdout.write(self.style.WARNING(f"Flood wait fixing holes for {channel}: {exc}"))
            if not settings.IGNORE_FLOODWAIT:
                sleep(settings.TELEGRAM_FLOODWAIT_SLEEP_SECONDS)
        except Exception as exc:
            printer.newline()
            self.stdout.write(self.style.WARNING(f"Error fixing holes for {channel}: {exc}"))
            logger.exception("fix_message_holes failed for %s", channel)

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
        try:
            crawler.fetch_channel_replies(
                channel,
                min_telegram_id=min_telegram_id,
                max_telegram_id=max_telegram_id,
                status_callback=lambda message, idx=index: printer.status(message, idx),
            )
            printer.ensure_newline()
        except errors.FloodWaitError as exc:
            printer.newline()
            self.stdout.write(self.style.WARNING(f"Flood wait fetching replies for {channel}: {exc}"))
            if not settings.IGNORE_FLOODWAIT:
                sleep(settings.TELEGRAM_FLOODWAIT_SLEEP_SECONDS)
        except Exception as exc:
            printer.newline()
            self.stdout.write(self.style.WARNING(f"Error fetching replies for {channel}: {exc}"))
            logger.exception("fetch_channel_replies failed for %s", channel)

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

        try:
            refresh_indent = " " * len(f"[{index}/{total_channels}] [id={channel.id}] ")
            crawler.refresh_message_stats(
                channel,
                telegram_channel,
                limit=refresh_limit,
                min_date=refresh_from,
                max_date=refresh_to,
                max_telegram_id=pre_crawl_max_id,
                status_callback=lambda message, ind=refresh_indent: printer.indented(message, ind),
            )
        except errors.FloodWaitError as error:
            printer.newline()
            self.stdout.write(
                self.style.WARNING(f"Skipping refresh for channel {channel.telegram_id} due to flood wait: {error}")
            )
            if not settings.IGNORE_FLOODWAIT:
                sleep(settings.TELEGRAM_FLOODWAIT_SLEEP_SECONDS)
        except errors.rpcerrorlist.ChannelPrivateError:
            printer.newline()
            self.stdout.write(
                self.style.WARNING(
                    f"Skipping refresh for channel {channel.telegram_id}: channel is private or inaccessible"
                )
            )
        except Exception as error:
            printer.newline()
            self.stdout.write(self.style.WARNING(f"Skipping refresh for channel {channel.telegram_id}: {error}"))
            logger.exception("Refresh failed for channel %s", channel.telegram_id)

    def _fix_missing_media(
        self,
        interesting_qs: Any,
        api_client: TelegramAPIClient,
        download_temp_dir: str,
        printer: ProgressPrinter,
    ) -> None:
        """Re-download media files that are absent from disk or were never fetched."""
        fix_handler = MediaHandler(
            api_client,
            download_temp_dir=download_temp_dir,
            download_images=True,
            download_video=True,
        )

        # Messages with photo/video media_type but no corresponding record
        needs_pic: set[int] = set(
            Message.objects.filter(channel__in=interesting_qs, media_type="photo")
            .filter(messagepicture__isnull=True)
            .values_list("id", flat=True)
        )
        needs_vid: set[int] = set(
            Message.objects.filter(channel__in=interesting_qs, media_type="video")
            .filter(messagevideo__isnull=True)
            .values_list("id", flat=True)
        )

        # Records that exist but whose file is missing on disk
        for mp in MessagePicture.objects.filter(message__channel__in=interesting_qs).select_related("message"):
            if mp.picture and not os.path.exists(mp.picture.path):
                needs_pic.add(mp.message_id)
        for mv in MessageVideo.objects.filter(message__channel__in=interesting_qs).select_related("message"):
            if mv.video and not os.path.exists(mv.video.path):
                needs_vid.add(mv.message_id)

        all_msg_pks = needs_pic | needs_vid
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
                    downloaded += 1
                    printer.status(
                        f"{channel_label} | downloaded {downloaded}/{n_messages}",
                        ch_idx,
                    )

            printer.ensure_newline()

        self.stdout.write(f"Missing media: {downloaded} downloaded, {skipped} skipped.")

    def handle(self, *args: Any, **options: Any) -> None:
        from django.core.management.base import CommandError

        # ── Channels options ───────────────────────────────────────────────────
        get_channels_info: bool = options["get_channels_info"]
        mine_about_texts: bool = options["mine_about_texts"]
        fetch_recommended: bool = options["fetch_recommended_channels"]
        retry_lost_and_private: bool = options["retry_lost_and_private"]
        # ── Messages options ───────────────────────────────────────────────────
        get_new_messages: bool = options["get_new_messages"]
        fetch_replies: bool = options["fetch_replies"]
        do_refresh: bool = options["refresh_messages_stats"]
        refresh_limit: int | None = options["refresh_limit"]
        fix_holes: bool = options["fixholes"]
        fix_missing_media: bool = options["fix_missing_media"]
        retry_references: bool = options["retry_references"]
        force_retry: bool = options["force_retry_unresolved_references"]
        # ── Refresh date window ────────────────────────────────────────────────
        refresh_from: datetime.date | None = None
        refresh_to: datetime.date | None = None
        for _raw, _flag, _attr in (
            (options.get("refresh_from"), "--refresh-from", "refresh_from"),
            (options.get("refresh_to"), "--refresh-to", "refresh_to"),
        ):
            if _raw is not None:
                if not _DATE_RE.match(_raw):
                    raise CommandError(f"{_flag}: expected YYYY-MM-DD, got {_raw!r}")
                if _attr == "refresh_from":
                    refresh_from = datetime.date.fromisoformat(_raw)
                else:
                    refresh_to = datetime.date.fromisoformat(_raw)
        # ── Degrees options ────────────────────────────────────────────────────
        in_degrees: bool = options["in_degrees"]
        out_degrees: bool = options["out_degrees"]
        # ── Scope ─────────────────────────────────────────────────────────────
        ids_str: str | None = options["ids"]
        channel_types_raw = options["channel_types"]
        channel_types = (
            [s.strip().upper() for s in channel_types_raw.split(",") if s.strip()]
            if channel_types_raw is not None
            else settings.DEFAULT_CHANNEL_TYPES
        )
        invalid_channel_types = [t for t in channel_types if t not in VALID_CHANNEL_TYPES]
        if invalid_channel_types:
            raise CommandError(
                f"Invalid --channel-types value(s): {invalid_channel_types!r}. Choose from {sorted(VALID_CHANNEL_TYPES)}."
            )
        interesting_qs = Channel.objects.filter(organization__is_interesting=True).filter(
            channel_type_filter(channel_types)
        )
        if not retry_lost_and_private:
            interesting_qs = interesting_qs.exclude(is_lost=True).exclude(is_private=True)
        channel_groups_raw = options.get("channel_groups")
        channel_groups = [s.strip() for s in channel_groups_raw.split(",") if s.strip()] if channel_groups_raw else []
        if channel_groups:
            interesting_qs = interesting_qs.filter(groups__name__in=channel_groups).distinct()

        need_client = (
            get_channels_info
            or mine_about_texts
            or fetch_recommended
            or get_new_messages
            or do_refresh
            or fix_holes
            or fix_missing_media
            or retry_references
            or fetch_replies
        )

        messages_limit: int | None = settings.TELEGRAM_CRAWLER_MESSAGES_LIMIT_PER_CHANNEL
        temp_root = settings.BASE_DIR / "tmp"
        temp_root.mkdir(exist_ok=True)
        download_temp_dir = tempfile.mkdtemp(prefix="crawl_channels_", dir=temp_root)

        warning_handler: _WarningLogHandler | None = None
        try:
            if need_client:
                with TelegramClient(
                    settings.TELEGRAM_SESSION_NAME,
                    settings.TELEGRAM_API_ID,
                    settings.TELEGRAM_API_HASH,
                    connection_retries=settings.TELEGRAM_CONNECTION_RETRIES,
                    retry_delay=settings.TELEGRAM_RETRY_DELAY,
                    flood_sleep_threshold=settings.TELEGRAM_FLOOD_SLEEP_THRESHOLD,
                ).start(phone=settings.TELEGRAM_PHONE_NUMBER) as client:
                    api_client = TelegramAPIClient(client)
                    media_handler = MediaHandler(
                        api_client,
                        download_temp_dir=download_temp_dir,
                        download_images=settings.TELEGRAM_CRAWLER_DOWNLOAD_IMAGES,
                        download_video=settings.TELEGRAM_CRAWLER_DOWNLOAD_VIDEO,
                    )
                    reference_resolver = ReferenceResolver(api_client)
                    crawler = ChannelCrawler(
                        api_client, media_handler, reference_resolver, messages_limit=messages_limit
                    )

                    channels = interesting_qs.order_by("-id")
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

                            # Type-excluded channels still get metadata updated.
                            all_interesting_base = (
                                Channel.objects.filter(organization__is_interesting=True)
                                .exclude(is_lost=True)
                                .exclude(is_private=True)
                            )
                            excluded_by_type = all_interesting_base.exclude(
                                channel_type_filter(channel_types)
                            ).order_by("-id")
                            if channel_groups:
                                excluded_by_type = excluded_by_type.filter(groups__name__in=channel_groups).distinct()
                            if ids_str:
                                excluded_by_type = excluded_by_type.filter(parse_id_ranges(ids_str))
                            n_excluded = excluded_by_type.count()
                            if n_excluded:
                                _meta_len: list[int] = [0]
                                self.stdout.write(
                                    f"\nUpdating metadata for {n_excluded} type-excluded channel(s)", ending=""
                                )
                                self.stdout.flush()
                                for i, meta_ch in enumerate(excluded_by_type.iterator(chunk_size=10), start=1):
                                    line = printer._fit(f"Metadata [{i}/{n_excluded}] {meta_ch}")
                                    padding = " " * max(0, _meta_len[0] - len(line))
                                    self.stdout.write(f"\r{line}{padding}", ending="")
                                    self.stdout.flush()
                                    _meta_len[0] = len(line)
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
                                    self.stdout.write(
                                        f"\nFetching {n_about} channels referenced in about texts", ending=""
                                    )
                                    self.stdout.flush()
                                    _about_len: list[int] = [0]
                                    fetched_about = 0
                                    for i, ref in enumerate(new_about_refs, start=1):
                                        line = printer._fit(f"About texts [{i}/{n_about}] {ref}")
                                        padding = " " * max(0, _about_len[0] - len(line))
                                        self.stdout.write(f"\r{line}{padding}", ending="")
                                        self.stdout.flush()
                                        _about_len[0] = len(line)
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
                            interesting_channels = list(channels)
                            n_rec = len(interesting_channels)
                            self.stdout.write(
                                f"\nFetching recommended channels for {n_rec} interesting channels",
                                ending="\n" if not printer._is_tty else "",
                            )
                            self.stdout.flush()
                            _rec_len: list[int] = [0]
                            rec_total = 0
                            rec_new = 0
                            for i, ch_rec in enumerate(interesting_channels, start=1):
                                line = printer._fit(f"Recommended channels [{i}/{n_rec}] {ch_rec}")
                                padding = " " * max(0, _rec_len[0] - len(line))
                                self.stdout.write(f"\r{line}{padding}", ending="")
                                self.stdout.flush()
                                _rec_len[0] = len(line)
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
                            self._fix_missing_media(channels, api_client, download_temp_dir, printer)

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
            interesting_pks = set(interesting_qs.values_list("pk", flat=True))

            cited_pks = (
                set(
                    Message.objects.filter(
                        channel__organization__is_interesting=True,
                        forwarded_from__isnull=False,
                    ).values_list("forwarded_from_id", flat=True)
                )
                | set(
                    Message.references.through.objects.filter(
                        message__channel__organization__is_interesting=True,
                    ).values_list("channel_id", flat=True)
                )
            ) - interesting_pks

            if in_degrees and interesting_pks:
                self.stdout.write("Refreshing degrees: computing citation counts…")
                self.stdout.flush()
                fwd_cited_by = set(
                    Message.objects.filter(
                        channel__organization__is_interesting=True,
                        forwarded_from_id__in=interesting_pks,
                    )
                    .exclude(channel_id=F("forwarded_from_id"))
                    .values_list("id", "forwarded_from_id")
                )
                ref_cited_by = set(
                    Message.references.through.objects.filter(
                        message__channel__organization__is_interesting=True,
                        channel_id__in=interesting_pks,
                    )
                    .exclude(message__channel_id=F("channel_id"))
                    .values_list("message_id", "channel_id")
                )
                cited_by_counts: Counter[int] = Counter(tgt for _, tgt in fwd_cited_by | ref_cited_by)

                fwd_cites = set(
                    Message.objects.filter(
                        channel_id__in=interesting_pks,
                        forwarded_from_id__in=interesting_pks,
                    )
                    .exclude(channel_id=F("forwarded_from_id"))
                    .values_list("channel_id", "id")
                )
                ref_cites = set(
                    Message.references.through.objects.filter(
                        message__channel_id__in=interesting_pks,
                        channel_id__in=interesting_pks,
                    )
                    .exclude(message__channel_id=F("channel_id"))
                    .values_list("message__channel_id", "message_id")
                )
                cites_counts: Counter[int] = Counter(src for src, _ in fwd_cites | ref_cites)

                channels_to_update = list(Channel.objects.filter(pk__in=interesting_pks))
                for ch in channels_to_update:
                    cited_by = cited_by_counts.get(ch.pk, 0)
                    cites = cites_counts.get(ch.pk, 0)
                    if settings.REVERSED_EDGES:
                        ch.in_degree, ch.out_degree = cited_by, cites
                    else:
                        ch.in_degree, ch.out_degree = cites, cited_by

                total = len(channels_to_update)
                _len: list[int] = [0]
                _deg_printer = ProgressPrinter(self.stdout, total)
                self.stdout.write(
                    f"\nRefreshing degrees for {total} interesting channels",
                    ending="\n" if not _deg_printer._is_tty else "",
                )
                self.stdout.flush()
                for i in range(0, total, 100):
                    Channel.objects.bulk_update(channels_to_update[i : i + 100], ["in_degree", "out_degree"])
                    done = min(i + 100, total)
                    line = _deg_printer._fit(f"Refreshing degrees for {total} interesting channels [{done}/{total}]")
                    if _deg_printer._is_tty:
                        padding = " " * max(0, _len[0] - len(line))
                        self.stdout.write(f"\r{line}{padding}", ending="")
                        self.stdout.flush()
                        _len[0] = len(line)
                    else:
                        self.stdout.write(line, ending="\n")
                        self.stdout.flush()
                if _deg_printer._is_tty:
                    self.stdout.write("", ending="\n")

            if out_degrees and cited_pks:
                fwd_cited = set(
                    Message.objects.filter(
                        channel__organization__is_interesting=True,
                        forwarded_from_id__in=cited_pks,
                    )
                    .exclude(channel_id=F("forwarded_from_id"))
                    .values_list("id", "forwarded_from_id")
                )
                ref_cited = set(
                    Message.references.through.objects.filter(
                        message__channel__organization__is_interesting=True,
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
                _len2: list[int] = [0]
                _deg_printer2 = ProgressPrinter(self.stdout, total)
                self.stdout.write(f"Refreshing citation degree for {total} referenced channels", ending="")
                self.stdout.flush()
                for i in range(0, total, 100):
                    Channel.objects.bulk_update(cited_channels[i : i + 100], ["in_degree", "out_degree"])
                    done = min(i + 100, total)
                    line = _deg_printer2._fit(
                        f"Refreshing citation degree for {total} referenced channels [{done}/{total}]"
                    )
                    padding = " " * max(0, _len2[0] - len(line))
                    self.stdout.write(f"\r{line}{padding}", ending="")
                    self.stdout.flush()
                    _len2[0] = len(line)
                self.stdout.write("", ending="\n")

        self.stdout.write(self.style.SUCCESS("\nCrawl complete."))
