from typing import Any

from django.conf import settings
from django.db.models import F
from django.utils import timezone

from crawler.channel_crawler import ChannelCrawler
from crawler.client import TelegramAPIClient
from crawler.media_handler import MediaHandler
from crawler.reference_resolver import ReferenceResolver
from webapp.models import SearchTerm
from webapp_engine.async_commands import AsyncBaseCommand

from telethon.sync import TelegramClient


class Command(AsyncBaseCommand):
    args = ""
    help = "crawling Telegram groups"

    def add_arguments(self, parser):
        parser.add_argument(
            "--amount",
            type=int,
            default=None,
            help="Number of search terms to process (default: all)",
        )

    def handle(self, *args: Any, **options: Any) -> None:
        qs = SearchTerm.objects.all().order_by(F("last_check").asc(nulls_first=True))
        if options["amount"] is not None:
            qs = qs[: options["amount"]]
        total_found = 0
        total_new = 0
        with TelegramClient(
            "anon",
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
        self.stdout.write(self.style.SUCCESS(f"\nSearch complete. {total_found} channels found, {total_new} new."))
