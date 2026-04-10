import datetime
import logging
import re
import shutil
import tempfile
from argparse import ArgumentParser
from collections import Counter
from typing import Any

from django.conf import settings
from django.db.models import F

from crawler.channel_crawler import ChannelCrawler
from crawler.client import TelegramAPIClient
from crawler.media_handler import MediaHandler
from crawler.reference_resolver import DEAD_PREFIX, SKIPPABLE_REFERENCES, ReferenceResolver
from webapp.models import Channel, Message
from webapp_engine.async_commands import AsyncBaseCommand

from telethon import errors
from telethon.sync import TelegramClient

logger = logging.getLogger(__name__)

_REFRESH_SKIP = object()  # sentinel: flag not provided at all
_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_ABOUT_REF_RE = re.compile(r"t\.me/((?:[-\w.]|(?:%[\da-fA-F]{2}))+)")


def _parse_refresh_arg(raw: Any) -> tuple[int | None, datetime.date | None]:
    """Return (limit, min_date) from the raw --refresh-messages-stats value.

    Possible inputs:
      _REFRESH_SKIP  → flag not given            → (skip, None)
      None           → bare flag, no value       → (None=all, None)
      "200"          → integer string            → (200, None)
      "2024-01-15"   → ISO date string           → (None, date(2024,1,15))
    Raises ValueError for unrecognised strings.
    """
    if raw is _REFRESH_SKIP:
        return _REFRESH_SKIP, None  # type: ignore[return-value]
    if raw is None:
        return None, None  # all messages, no date filter
    raw = str(raw)
    if _DATE_RE.match(raw):
        return None, datetime.date.fromisoformat(raw)
    try:
        return int(raw), None
    except ValueError as exc:
        raise ValueError(f"--refresh-messages-stats: expected an integer or YYYY-MM-DD date, got {raw!r}") from exc


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


class Command(AsyncBaseCommand):
    args = ""
    help = "crawling Telegram groups"

    def add_arguments(self, parser: ArgumentParser) -> None:
        parser.add_argument(
            "--fixholes",
            action="store_true",
            default=False,
            help="Check channel message ids for holes and fetch missing messages",
        )
        parser.add_argument(
            "--fromid",
            type=int,
            default=None,
            metavar="ID",
            help="Only crawl channels whose database id is less than or equal to this value.",
        )
        parser.add_argument(
            "--fetch-recommended-channels",
            action="store_true",
            default=False,
            help=(
                "After crawling, fetch Telegram-recommended channels for each interesting channel "
                "and add any new ones to the database. New channels are not crawled automatically; "
                "mark them as interesting to include them in the next run."
            ),
        )
        parser.add_argument(
            "--force-retry-unresolved-references",
            action="store_true",
            default=False,
            help=(
                "Retry all unresolved message references, including those already marked as permanently "
                "unresolvable (e.g. deleted channels). By default, permanently dead references are skipped."
            ),
        )
        parser.add_argument(
            "--refresh-messages-stats",
            nargs="?",
            const=None,
            default=_REFRESH_SKIP,
            metavar="N|YYYY-MM-DD",
            help=(
                "After crawling each channel, re-fetch messages and update views, forwards, "
                "and pinned status. Accepts three forms: "
                "omit the value to refresh all messages; "
                "pass an integer N to refresh only the N most recent messages; "
                "pass a date (YYYY-MM-DD) to refresh all messages from that date to the present. "
                "The flag has no effect when not provided."
            ),
        )

    def _refresh_channel(
        self,
        channel: Channel,
        crawler: ChannelCrawler,
        index: int,
        total_channels: int,
        refresh_limit: int | None,
        refresh_min_date: datetime.date | None,
        pre_crawl_max_id: int,
        printer: ProgressPrinter,
    ) -> None:
        try:
            telegram_channel = crawler.api_client.client.get_entity(channel.telegram_id)
            refresh_indent = " " * len(f"[{index}/{total_channels}] [id={channel.id}] ")
            crawler.refresh_message_stats(
                channel,
                telegram_channel,
                limit=refresh_limit,
                min_date=refresh_min_date,
                max_telegram_id=pre_crawl_max_id,
                status_callback=lambda message, ind=refresh_indent: printer.indented(message, ind),
            )
        except errors.FloodWaitError as error:
            printer.newline()
            self.stdout.write(
                self.style.WARNING(f"Skipping refresh for channel {channel.telegram_id} due to flood wait: {error}")
            )
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

    def handle(self, *args: Any, **options: Any) -> None:
        fix_holes: bool = options["fixholes"]
        fetch_recommended: bool = options["fetch_recommended_channels"]
        force_retry: bool = options["force_retry_unresolved_references"]
        try:
            refresh_limit, refresh_min_date = _parse_refresh_arg(options["refresh_messages_stats"])
        except ValueError as exc:
            from django.core.management.base import CommandError

            raise CommandError(str(exc)) from exc
        do_refresh = refresh_limit is not _REFRESH_SKIP
        fromid: int | None = options["fromid"]
        messages_limit: int | None = settings.TELEGRAM_CRAWLER_MESSAGES_LIMIT_PER_CHANNEL
        temp_root = settings.BASE_DIR / "tmp"
        temp_root.mkdir(exist_ok=True)
        download_temp_dir = tempfile.mkdtemp(prefix="get_channels_", dir=temp_root)

        warning_handler: _WarningLogHandler | None = None
        try:
            with TelegramClient(
                "anon",
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
                crawler = ChannelCrawler(api_client, media_handler, reference_resolver, messages_limit=messages_limit)

                channels = Channel.objects.interesting().order_by("-id")
                if fromid is not None:
                    channels = channels.filter(id__lte=fromid)
                total_channels = channels.count()
                printer = ProgressPrinter(self.stdout, total_channels)
                warning_handler = _WarningLogHandler(printer, self.style)
                logging.getLogger().addHandler(warning_handler)

                for index, channel in enumerate(channels.iterator(chunk_size=10), start=1):
                    try:
                        pre_crawl_max_id = crawler.get_channel(
                            channel.telegram_id,
                            fix_holes=fix_holes,
                            status_callback=lambda message, idx=index: printer.status(message, idx),
                        )
                    except errors.FloodWaitError as error:
                        printer.newline()
                        self.stdout.write(
                            self.style.WARNING(
                                f"Skipping channel {channel.telegram_id} due to flood wait while resolving references: {error}"
                            )
                        )
                        continue
                    printer.ensure_newline()
                    if do_refresh:
                        self._refresh_channel(
                            channel,
                            crawler,
                            index,
                            total_channels,
                            refresh_limit,
                            refresh_min_date,
                            pre_crawl_max_id,
                            printer,
                        )

                printer.newline()

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

                    def _ref_progress(done: int, total: int) -> None:
                        line = printer._fit(f"Retrying unresolved message references [{done}/{total}]")
                        padding = " " * max(0, _ref_len[0] - len(line))
                        self.stdout.write(f"\r{line}{padding}", ending="")
                        self.stdout.flush()
                        _ref_len[0] = len(line)

                    self.stdout.write(f"\nRetrying {n_missing} unresolved message references", ending="")
                    self.stdout.flush()
                    crawler.get_missing_references(status_callback=_ref_progress, force_retry=force_retry)
                    self.stdout.write("", ending="\n")

                # ---- mine Channel.about for t.me/ references ----
                about_refs: set[str] = set()
                for about_text in Channel.objects.interesting().exclude(about="").values_list("about", flat=True):
                    for m in _ABOUT_REF_RE.finditer(about_text):
                        ref = m.group(1).strip().lower()
                        if ref and ref not in SKIPPABLE_REFERENCES:
                            about_refs.add(ref)

                if about_refs:
                    known_lower = {
                        u.lower() for u in Channel.objects.exclude(username="").values_list("username", flat=True)
                    }
                    new_about_refs = sorted(about_refs - known_lower)
                    if new_about_refs:
                        n_about = len(new_about_refs)
                        self.stdout.write(f"\nFetching {n_about} channels referenced in about texts", ending="")
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
                                channel, _ = crawler.get_basic_channel(ref)
                                if channel:
                                    fetched_about += 1
                            except errors.FloodWaitError as exc:
                                self.stdout.write("", ending="\n")
                                self.stdout.write(
                                    self.style.WARNING(f"Flood wait while fetching about references: {exc}")
                                )
                                break
                            except ValueError:
                                pass  # user account, not a channel
                            except Exception as exc:
                                logger.warning("Error fetching about reference %s: %s", ref, exc)
                        self.stdout.write("", ending="\n")
                        self.stdout.write(f"About texts: {fetched_about}/{n_about} new channels fetched.")
                    else:
                        self.stdout.write("\nAbout texts: all referenced channels already in DB.")

                # ---- fetch Telegram-recommended channels ----
                if fetch_recommended:
                    interesting_channels = list(Channel.objects.interesting())
                    n_rec = len(interesting_channels)
                    self.stdout.write(f"\nFetching recommended channels for {n_rec} interesting channels", ending="")
                    self.stdout.flush()
                    _rec_len: list[int] = [0]
                    rec_total = 0
                    rec_new = 0
                    for i, channel in enumerate(interesting_channels, start=1):
                        line = printer._fit(f"Recommended channels [{i}/{n_rec}] {channel}")
                        padding = " " * max(0, _rec_len[0] - len(line))
                        self.stdout.write(f"\r{line}{padding}", ending="")
                        self.stdout.flush()
                        _rec_len[0] = len(line)
                        try:
                            found, new = crawler.get_recommended_channels(channel)
                            rec_total += found
                            rec_new += new
                        except errors.FloodWaitError as exc:
                            self.stdout.write("", ending="\n")
                            self.stdout.write(
                                self.style.WARNING(f"Flood wait while fetching recommended channels: {exc}")
                            )
                            break
                        except Exception as exc:
                            logger.warning("Error fetching recommended channels for %s: %s", channel, exc)
                    self.stdout.write("", ending="\n")
                    self.stdout.write(f"Recommended channels: {rec_total} found, {rec_new} new.")

                media_handler.clean_leftovers()
            # The TelegramClient context manager has now exited and the connection
            # is closed.  Any "Server closed the connection" warning from Telethon
            # is emitted here, while warning_handler is still attached, so it will
            # be coloured correctly.
        finally:
            if warning_handler is not None:
                logging.getLogger().removeHandler(warning_handler)
            shutil.rmtree(download_temp_dir, ignore_errors=True)

        interesting_pks = set(Channel.objects.interesting().values_list("pk", flat=True))

        # Non-interesting channels cited by interesting channels: via forwards or t.me/username references.
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

        if interesting_pks:
            # Build (message_id, target_channel_id) pairs for all citations toward interesting channels,
            # taking the union of forward-from and reference links so each message counts once per target.
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

            # Outgoing: messages from each interesting channel that cite another interesting channel.
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
            self.stdout.write(f"\nRefreshing degrees for {total} interesting channels", ending="")
            self.stdout.flush()
            for i in range(0, total, 100):
                Channel.objects.bulk_update(channels_to_update[i : i + 100], ["in_degree", "out_degree"])
                done = min(i + 100, total)
                line = printer._fit(f"Refreshing degrees for {total} interesting channels [{done}/{total}]")
                padding = " " * max(0, _len[0] - len(line))
                self.stdout.write(f"\r{line}{padding}", ending="")
                self.stdout.flush()
                _len[0] = len(line)
            self.stdout.write("", ending="\n")

        if cited_pks:
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
            self.stdout.write(f"Refreshing citation degree for {total} referenced channels", ending="")
            self.stdout.flush()
            for i in range(0, total, 100):
                Channel.objects.bulk_update(cited_channels[i : i + 100], ["in_degree", "out_degree"])
                done = min(i + 100, total)
                line = printer._fit(f"Refreshing citation degree for {total} referenced channels [{done}/{total}]")
                padding = " " * max(0, _len2[0] - len(line))
                self.stdout.write(f"\r{line}{padding}", ending="")
                self.stdout.flush()
                _len2[0] = len(line)
            self.stdout.write("", ending="\n")

        self.stdout.write(self.style.SUCCESS("\nCrawl complete."))
