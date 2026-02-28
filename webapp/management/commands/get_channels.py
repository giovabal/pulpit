from django.conf import settings
from django.core.management.base import BaseCommand

from webapp.crawler import TelegramCrawler
from webapp.models import Channel

from telethon import errors
from telethon.sync import TelegramClient


class Command(BaseCommand):
    args = ""
    help = "crawling Telegram groups"

    def handle(self, *args, **options):
        self._ensure_event_loop()
        with TelegramClient("anon", settings.TELEGRAM_API_ID, settings.TELEGRAM_API_HASH).start(
            phone=settings.TELEGRAM_PHONE_NUMBER
        ) as client:
            crawler = TelegramCrawler(client)

            channels = Channel.objects.filter(organization__is_interesting=True).order_by("-id")
            total_channels = channels.count()

            def print_status(message):
                self.stdout.write(f"\r{message}", ending="")
                self.stdout.flush()

            for index, channel in enumerate(channels.iterator(chunk_size=10), start=1):
                try:
                    crawler.get_channel(
                        channel.telegram_id,
                        status_callback=lambda message, idx=index: print_status(f"[{idx}/{total_channels}] {message}"),
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
            crawler.clean_leftovers()

        for c in Channel.objects.filter(organization__is_interesting=False):
            c.save()
