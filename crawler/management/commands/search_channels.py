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

from telethon.sync import TelegramClient


class Command(BaseCommand):
    args = ""
    help = "crawling Telegram groups"

    def add_arguments(self, parser):
        parser.add_argument(
            "--amount",
            type=int,
            default=None,
            help="Number of database search terms to process (default: all).",
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
            for term in qs:
                self.stdout.write(f'Searching: "{term.word}" … ', ending="")
                self.stdout.flush()
                found, new = crawler.search_channel(term.word)
                self.stdout.write(f"{found} found, {new} new")
                total_found += found
                total_new += new
                term.last_check = timezone.now()
                term.save(update_fields=["last_check"])
            for word in extra_terms:
                self.stdout.write(f'Searching (extra): "{word}" … ', ending="")
                self.stdout.flush()
                found, new = crawler.search_channel(word)
                self.stdout.write(f"{found} found, {new} new")
                total_found += found
                total_new += new
        self.stdout.write(self.style.SUCCESS(f"\nSearch complete. {total_found} channels found, {total_new} new."))
