import shutil
import tempfile

from django.conf import settings

from crawler.channel_crawler import ChannelCrawler
from crawler.client import TelegramAPIClient
from crawler.media_handler import MediaHandler
from crawler.reference_resolver import ReferenceResolver
from webapp.management import AsyncBaseCommand
from webapp.models import Channel

from telethon import errors
from telethon.sync import TelegramClient


class Command(AsyncBaseCommand):
    args = ""
    help = "crawling Telegram groups"

    def add_arguments(self, parser):
        parser.add_argument(
            "--fixholes",
            action="store_true",
            default=False,
            help="Check channel message ids for holes and fetch missing messages",
        )

    def handle(self, *args, **options):
        self._ensure_event_loop()
        fix_holes = options["fixholes"]
        temp_root = settings.BASE_DIR / "tmp"
        temp_root.mkdir(exist_ok=True)
        download_temp_dir = tempfile.mkdtemp(prefix="get_channels_", dir=temp_root)

        try:
            with TelegramClient("anon", settings.TELEGRAM_API_ID, settings.TELEGRAM_API_HASH).start(
                phone=settings.TELEGRAM_PHONE_NUMBER
            ) as client:
                api_client = TelegramAPIClient(client)
                media_handler = MediaHandler(api_client, download_temp_dir=download_temp_dir)
                reference_resolver = ReferenceResolver(api_client)
                crawler = ChannelCrawler(api_client, media_handler, reference_resolver)

                channels = Channel.objects.interesting().order_by("-id")
                total_channels = channels.count()

                current_progress_channel = None
                last_line_length = 0

                def print_status(message, channel_index):
                    nonlocal current_progress_channel, last_line_length
                    if current_progress_channel != channel_index:
                        if current_progress_channel is not None:
                            self.stdout.write("", ending="\n")
                        current_progress_channel = channel_index
                        last_line_length = 0

                    line = f"[{channel_index}/{total_channels}] {message}"
                    padding = " " * max(0, last_line_length - len(line))
                    self.stdout.write(f"\r{line}{padding}", ending="")
                    self.stdout.flush()
                    last_line_length = len(line)

                for index, channel in enumerate(channels.iterator(chunk_size=10), start=1):
                    try:
                        crawler.get_channel(
                            channel.telegram_id,
                            fix_holes=fix_holes,
                            status_callback=lambda message, idx=index: print_status(message, idx),
                        )
                    except errors.FloodWaitError as error:
                        self.stdout.write("", ending="\n")
                        self.stdout.write(
                            self.style.WARNING(
                                f"Skipping channel {channel.telegram_id} due to flood wait while resolving references: {error}"
                            )
                        )
                        continue

                self.stdout.write(self.style.NOTICE("Retrying unresolved message references"))
                crawler.get_missing_references()

                self.stdout.write("", ending="\n")
                media_handler.clean_leftovers()
        finally:
            shutil.rmtree(download_temp_dir, ignore_errors=True)

        for c in Channel.objects.filter(organization__is_interesting=False):
            c.save()
