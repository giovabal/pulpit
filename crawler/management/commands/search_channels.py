from django.conf import settings
from django.db.models import F
from django.utils import timezone

from crawler.channel_crawler import ChannelCrawler
from crawler.client import TelegramAPIClient
from crawler.media_handler import MediaHandler
from crawler.reference_resolver import ReferenceResolver
from webapp.management import AsyncBaseCommand
from webapp.models import SearchTerm

from telethon.sync import TelegramClient


class Command(AsyncBaseCommand):
    args = ""
    help = "crawling Telegram groups"

    def handle(self, *args, **options):
        self._ensure_event_loop()
        with TelegramClient("anon", settings.TELEGRAM_API_ID, settings.TELEGRAM_API_HASH).start(
            phone=settings.TELEGRAM_PHONE_NUMBER
        ) as client:
            api_client = TelegramAPIClient(client)
            media_handler = MediaHandler(api_client)
            reference_resolver = ReferenceResolver(api_client)
            crawler = ChannelCrawler(api_client, media_handler, reference_resolver)
            for term in SearchTerm.objects.all().order_by(F("last_check").asc(nulls_first=True))[:15]:
                crawler.search_channel(term.word)
                term.last_check = timezone.now()
                term.save(update_fields=["last_check"])
