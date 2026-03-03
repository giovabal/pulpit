from datetime import datetime, timedelta
from time import sleep

from django.conf import settings
from django.utils import timezone

from telethon.sync import TelegramClient


class TelegramAPIClient:
    """Thin wrapper around a Telethon client that enforces rate limiting."""

    def __init__(self, client: TelegramClient) -> None:
        self.client: TelegramClient = client
        self.wait_time: int = settings.TELEGRAM_CRAWLER_GRACE_TIME
        self.last_call: datetime = timezone.now() - timedelta(seconds=self.wait_time)

    def wait(self) -> None:
        w = self.wait_time - (timezone.now() - self.last_call).total_seconds()
        if w > 0:
            sleep(w)
        self.last_call = timezone.now()
