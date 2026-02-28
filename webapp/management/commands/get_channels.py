from django.conf import settings
from django.core.management.base import BaseCommand

from webapp.crawler import TelegramCrawler
from webapp.models import Channel
from webapp.management import AsyncBaseCommand

from telethon import errors
from telethon.sync import TelegramClient


class Command(AsyncBaseCommand):
    args = ""
    help = "crawling Telegram groups"

    def handle(self, *args, **options):
        self._ensure_event_loop()
        with TelegramClient("anon", settings.TELEGRAM_API_ID, settings.TELEGRAM_API_HASH).start(
            phone=settings.TELEGRAM_PHONE_NUMBER
        ) as client:
            crawler = TelegramCrawler(client)
            for channel in (
                Channel.objects.filter(organization__is_interesting=True).order_by("-id").iterator(chunk_size=10)
            ):
                try:
                    crawler.get_channel(channel.telegram_id)
                except errors.FloodWaitError as error:
                    self.stdout.write(
                        self.style.WARNING(
                            f"Skipping channel {channel.telegram_id} due to flood wait while resolving references: {error}"
                        )
                    )
                    continue

            crawler.clean_leftovers()

        for c in Channel.objects.filter(organization__is_interesting=False):
            c.save()
