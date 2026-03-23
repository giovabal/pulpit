import datetime
import logging
import re
import shutil
import tempfile
from argparse import ArgumentParser
from typing import Any

from django.conf import settings

from crawler.channel_crawler import ChannelCrawler
from crawler.client import TelegramAPIClient
from crawler.media_handler import MediaHandler
from crawler.reference_resolver import ReferenceResolver
from webapp.management import AsyncBaseCommand
from webapp.models import Channel

from telethon import errors
from telethon.sync import TelegramClient

logger = logging.getLogger(__name__)

_REFRESH_SKIP = object()  # sentinel: flag not provided at all
_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


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

    def status(self, message: str, channel_index: int) -> None:
        if self._current_channel != channel_index:
            if self._current_channel is not None:
                self._stdout.write("", ending="\n")
            self._current_channel = channel_index
            self._line_length = 0
        line = f"[{channel_index}/{self._total}] {message}"
        padding = " " * max(0, self._line_length - len(line))
        self._stdout.write(f"\r{line}{padding}", ending="")
        self._stdout.flush()
        self._line_length = len(line)

    def indented(self, message: str, indent: str) -> None:
        line = f"{indent}{message}"
        padding = " " * max(0, self._line_length - len(line))
        self._stdout.write(f"\r{line}{padding}", ending="")
        self._stdout.flush()
        self._line_length = len(line)

    def newline(self) -> None:
        self._stdout.write("", ending="\n")
        self._line_length = 0
        self._current_channel = None


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
        try:
            refresh_limit, refresh_min_date = _parse_refresh_arg(options["refresh_messages_stats"])
        except ValueError as exc:
            from django.core.management.base import CommandError

            raise CommandError(str(exc)) from exc
        do_refresh = refresh_limit is not _REFRESH_SKIP
        fromid: int | None = options["fromid"]
        temp_root = settings.BASE_DIR / "tmp"
        temp_root.mkdir(exist_ok=True)
        download_temp_dir = tempfile.mkdtemp(prefix="get_channels_", dir=temp_root)

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
                media_handler = MediaHandler(api_client, download_temp_dir=download_temp_dir)
                reference_resolver = ReferenceResolver(api_client)
                crawler = ChannelCrawler(api_client, media_handler, reference_resolver)

                channels = Channel.objects.interesting().order_by("-id")
                if fromid is not None:
                    channels = channels.filter(id__lte=fromid)
                total_channels = channels.count()
                printer = ProgressPrinter(self.stdout, total_channels)

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
                    printer.newline()
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

                self.stdout.write(self.style.NOTICE("\nRetrying unresolved message references … "), ending="")
                self.stdout.flush()
                crawler.get_missing_references()
                self.stdout.write("done")

                media_handler.clean_leftovers()
        finally:
            shutil.rmtree(download_temp_dir, ignore_errors=True)

        referenced_pks = set(
            Channel.objects.filter(organization__is_interesting=True)
            .exclude(message_set__forwarded_from__isnull=True)
            .values_list("message_set__forwarded_from_id", flat=True)
            .distinct()
        )
        interesting_pks = set(Channel.objects.interesting().values_list("pk", flat=True))
        all_pks = interesting_pks | referenced_pks
        self.stdout.write(f"\nRefreshing degrees for {len(all_pks)} channels … ", ending="")
        self.stdout.flush()
        for channel in Channel.objects.filter(pk__in=all_pks):
            channel.refresh_degrees()
        self.stdout.write("done")

        self.stdout.write(self.style.SUCCESS("\nCrawl complete."))
