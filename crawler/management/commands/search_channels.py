import logging
from time import sleep
from typing import Any

from django.conf import settings
from django.core.management.base import BaseCommand
from django.db.models import F
from django.utils import timezone

from crawler.channel_crawler import ChannelCrawler
from crawler.client import TelegramAPIClient
from crawler.media_handler import MediaHandler
from crawler.reference_resolver import ReferenceResolver
from webapp.models import SearchTerm
from webapp_engine.command_logging import styled_warning_logs

from telethon import errors
from telethon.sync import TelegramClient

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    args = ""
    help = "crawling Telegram groups"

    def add_arguments(self, parser):
        parser.add_argument(
            "--amount",
            type=int,
            default=None,
            help="Number of database search terms to process (default: all; 0 = none, only --extra-term).",
        )
        parser.add_argument(
            "--extra-term",
            dest="extra_terms",
            action="append",
            default=[],
            metavar="TERM",
            help=(
                "Additional search term to process alongside database terms. "
                "Can be repeated. Terms are not persisted unless the Operations "
                "panel 'Save to database' checkbox was checked before launching."
            ),
        )

    def handle(self, *args: Any, **options: Any) -> None:
        # Route logger.warning/error lines (own modules, telethon) through
        # self.style so they carry severity colour in the Operations panel.
        with styled_warning_logs(self.style):
            self._handle(*args, **options)

    def _handle(self, *args: Any, **options: Any) -> None:
        qs = SearchTerm.objects.all().order_by(F("last_check").asc(nulls_first=True))
        if options["amount"] is not None:
            qs = qs[: options["amount"]]
        extra_terms = [t for t in (options.get("extra_terms") or []) if t]
        total_found = 0
        total_new = 0
        with TelegramClient(
            settings.TELEGRAM_SESSION_NAME,
            settings.TELEGRAM_API_ID,
            settings.TELEGRAM_API_HASH,
            connection_retries=settings.TELEGRAM_CONNECTION_RETRIES,
            retry_delay=settings.TELEGRAM_RETRY_DELAY,
            flood_sleep_threshold=settings.TELEGRAM_FLOOD_SLEEP_THRESHOLD,
        ).start(phone=settings.TELEGRAM_PHONE_NUMBER) as client:
            api_client = TelegramAPIClient(client)
            media_handler = MediaHandler(api_client)
            reference_resolver = ReferenceResolver(api_client)
            crawler = ChannelCrawler(api_client, media_handler, reference_resolver)
            searched_words: set[str] = set()
            for term in qs:
                result = self._run_search(crawler, term.word, "Searching: ")
                searched_words.add(term.word)  # term.word is already normalised by SearchTerm.save()
                if result is None:
                    continue  # leave last_check untouched so a failed term is retried first next run
                found, new = result
                total_found += found
                total_new += new
                term.last_check = timezone.now()
                term.save(update_fields=["last_check"])
            for word in extra_terms:
                # A term saved to the database before launch (Operations panel "Save to
                # database") is also passed as --extra-term; skip it here so it is not
                # searched twice in the same run. Normalise to match SearchTerm.save().
                if " ".join(word.split()).lower() in searched_words:
                    continue
                result = self._run_search(crawler, word, "Searching (extra): ")
                if result is None:
                    continue
                found, new = result
                total_found += found
                total_new += new
        self.stdout.write(self.style.SUCCESS(f"\nSearch complete. {total_found} channels found, {total_new} new."))

    def _run_search(self, crawler: ChannelCrawler, word: str, label: str) -> tuple[int, int] | None:
        """Run one search term; return (found, new), or None if it failed so the run can continue.

        A single bad term (RPCError, above-threshold flood wait, network error) must not abort the
        whole command — log it and move on, mirroring the per-channel resilience of crawl_channels.
        """
        self.stdout.write(f'{label}"{word}" … ', ending="")
        self.stdout.flush()
        try:
            found, new = crawler.search_channel(word)
        except errors.FloodWaitError as exc:
            self.stdout.write(self.style.WARNING(f"flood wait, skipping: {exc}"))
            if not settings.IGNORE_FLOODWAIT:
                sleep(settings.TELEGRAM_FLOODWAIT_SLEEP_SECONDS)
            return None
        except Exception as exc:  # noqa: BLE001 - one bad term must not abort the whole run
            logger.warning("Search failed for term %r: %s", word, exc)
            self.stdout.write(self.style.WARNING(f"failed: {exc}"))
            return None
        self.stdout.write(f"{found} found, {new} new")
        return found, new
