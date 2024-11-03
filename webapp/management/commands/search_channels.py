from django.conf import settings
from django.core.management.base import BaseCommand
from django.utils import timezone

from webapp.crawler import TelegramCrawler
from webapp.models import SearchTerm

from telethon import TelegramClient


class Command(BaseCommand):
    args = ""
    help = "crawling Telegram groups"

    def handle(self, *args, **options):
        with TelegramClient("anon", settings.TELEGRAM_API_ID, settings.TELEGRAM_API_HASH).start(
            phone=settings.TELEGRAM_PHONE_NUMBER
        ) as client:
            crawler = TelegramCrawler(client)
            for term in SearchTerm.objects.all().order_by("last_check")[:15]:
                word = term.word
                print(word, crawler.search_channel(word))
                term.last_check = timezone.now()
                term.save(update_fields=["last_check"])
