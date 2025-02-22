from django.conf import settings
from django.core.management.base import BaseCommand

from webapp.crawler import TelegramCrawler
from webapp.models import Channel

from telethon.sync import TelegramClient


class Command(BaseCommand):
    args = ""
    help = "crawling Telegram groups"

    def handle(self, *args, **options):
        with TelegramClient("anon", settings.TELEGRAM_API_ID, settings.TELEGRAM_API_HASH).start(
            phone=settings.TELEGRAM_PHONE_NUMBER
        ) as client:
            crawler = TelegramCrawler(client)
            for channel in (
                Channel.objects.filter(organization__is_interesting=True).order_by("-id").iterator(chunk_size=10)
            ):
                crawler.get_channel(channel.telegram_id)

            crawler.clean_leftovers()

        for c in Channel.objects.filter(organization__is_interesting=False):
            c.save()
