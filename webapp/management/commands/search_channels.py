import asyncio

from django.conf import settings
from django.core.management.base import BaseCommand
from django.db.models import F
from django.utils import timezone

from webapp.crawler import TelegramCrawler
from webapp.models import SearchTerm

from telethon.sync import TelegramClient


class Command(BaseCommand):
    args = ""
    help = "crawling Telegram groups"

    def _ensure_event_loop(self):
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            asyncio.set_event_loop(asyncio.new_event_loop())

    def handle(self, *args, **options):
        self._ensure_event_loop()
        with TelegramClient("anon", settings.TELEGRAM_API_ID, settings.TELEGRAM_API_HASH).start(
            phone=settings.TELEGRAM_PHONE_NUMBER
        ) as client:
            crawler = TelegramCrawler(client)
            for term in SearchTerm.objects.all().order_by(F("last_check").asc(nulls_first=True))[:15]:
                crawler.search_channel(term.word)
                term.last_check = timezone.now()
                term.save(update_fields=["last_check"])
