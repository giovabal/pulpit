from django.conf import settings
from django.core.management.base import BaseCommand

from webapp.crawler import TelegramCrawler
from webapp.models import Channel

from telethon import TelegramClient


class Command(BaseCommand):
    args = ""
    help = "crawling Telegram groups"

    def add_arguments(self, parser):
        super().add_arguments(parser)
        parser.add_argument("--file-only", action="store_true", dest="file_only", default=False)

    def handle(self, *args, **options):
        file_only = options.pop("file_only")
        with TelegramClient("anon", settings.TELEGRAM_API_ID, settings.TELEGRAM_API_HASH).start(
            phone=settings.TELEGRAM_PHONE_NUMBER
        ) as client:
            crawler = TelegramCrawler(client)
            with open("username_seeds.txt") as f:
                for seed in f.readlines():
                    crawler.get_channel("t.me/{}".format(seed.strip()))

            if not file_only:
                for channel in (
                    Channel.objects.filter(is_interesting=True, is_lost=False).order_by("-id").iterator(chunk_size=10)
                ):
                    crawler.get_channel(channel.telegram_id)

            crawler.clean_leftovers()

        for c in Channel.objects.filter(is_interesting=False):
            c.save()
