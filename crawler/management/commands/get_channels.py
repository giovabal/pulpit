import datetime
import logging
import re
import shutil
import tempfile
from argparse import ArgumentParser
from typing import Any

from django.conf import settings
from django.db import connection

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

                current_progress_channel: int | None = None
                last_line_length = 0

                def print_status(message: str, channel_index: int) -> None:
                    nonlocal current_progress_channel, last_line_length
                    if current_progress_channel != channel_index:
                        if current_progress_channel is not None:
                            self.stdout.write("", ending="\n")
                        current_progress_channel = channel_index
                        last_line_length = 0

                    line = f"[{channel_index}/{total_channels}] {message}"
                    padding = " " * max(0, last_line_length - len(line))
                    self.stdout.write(f"\r{line}{padding}", ending="")
                    self.stdout.flush()
                    last_line_length = len(line)

                def print_indented(message: str, indent: str) -> None:
                    nonlocal last_line_length
                    line = f"{indent}{message}"
                    padding = " " * max(0, last_line_length - len(line))
                    self.stdout.write(f"\r{line}{padding}", ending="")
                    self.stdout.flush()
                    last_line_length = len(line)

                for index, channel in enumerate(channels.iterator(chunk_size=10), start=1):
                    try:
                        pre_crawl_max_id = crawler.get_channel(
                            channel.telegram_id,
                            fix_holes=fix_holes,
                            status_callback=lambda message, idx=index: print_status(message, idx),
                        )
                    except errors.FloodWaitError as error:
                        self.stdout.write("", ending="\n")
                        self.stdout.write(
                            self.style.WARNING(
                                f"Skipping channel {channel.telegram_id} due to flood wait while resolving references: {error}"
                            )
                        )
                        continue
                    self.stdout.write("", ending="\n")
                    last_line_length = 0
                    current_progress_channel = None
                    # Close the DB connection after each channel so SQLite does not
                    # accumulate stale internal state across a long crawl session.
                    connection.close()
                    if do_refresh:
                        try:
                            telegram_channel = crawler.api_client.client.get_entity(channel.telegram_id)
                            refresh_indent = " " * len(f"[{index}/{total_channels}] [id={channel.id}] ")
                            crawler.refresh_message_stats(
                                channel,
                                telegram_channel,
                                limit=refresh_limit,
                                min_date=refresh_min_date,
                                max_telegram_id=pre_crawl_max_id,
                                status_callback=lambda message, ind=refresh_indent: print_indented(message, ind),
                            )
                        except errors.FloodWaitError as error:
                            self.stdout.write("", ending="\n")
                            self.stdout.write(
                                self.style.WARNING(
                                    f"Skipping refresh for channel {channel.telegram_id} due to flood wait: {error}"
                                )
                            )
                        except Exception as error:
                            self.stdout.write("", ending="\n")
                            self.stdout.write(
                                self.style.WARNING(f"Skipping refresh for channel {channel.telegram_id}: {error}")
                            )
                            logger.exception("Refresh failed for channel %s", channel.telegram_id)

                self.stdout.write("", ending="\n")

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
