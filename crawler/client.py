from datetime import timedelta
from time import sleep

from django.conf import settings
from django.utils import timezone


class TelegramAPIClient:
    """Thin wrapper around a Telethon client that enforces rate limiting."""

    def __init__(self, client):
        self.client = client
        self.wait_time = settings.TELEGRAM_CRAWLER_GRACE_TIME  # seconds
        self.last_call = timezone.now() - timedelta(seconds=self.wait_time)

    def wait(self):
        w = self.wait_time - (timezone.now() - self.last_call).seconds
        if w > 0:
            sleep(w)
        self.last_call = timezone.now()
