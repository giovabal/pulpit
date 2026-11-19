"""Give every channel found commenting as itself a row in the channels list (crawler/commenting_channels.py).

Replies fetched from now on store their commenting channels as they arrive; this command does the same
for the replies already stored. ``--dry-run`` lists the candidates from the database and the Telethon
session cache alone — no Telegram call, no write.
"""

from time import sleep
from typing import Any

from django.conf import settings
from django.core.management.base import BaseCommand

from crawler.channel_crawler import ChannelCrawler
from crawler.client import TelegramAPIClient
from crawler.commenting_channels import (
    STATUS_LIVE,
    STATUS_LOST,
    STATUS_PRIVATE,
    STATUS_USER_CLASH,
    CommentingChannel,
    cached_entities,
    recover_commenting_channels,
    unknown_commenting_channels,
)
from crawler.media_handler import MediaHandler
from crawler.reference_resolver import ReferenceResolver
from webapp_engine.command_logging import styled_warning_logs

from telethon import errors
from telethon.sync import TelegramClient

_OUTCOMES = {
    STATUS_LIVE: "added (live)",
    STATUS_PRIVATE: "added (private — deleted, or closed to this account)",
    STATUS_LOST: "added (lost — not found on Telegram)",
    STATUS_USER_CLASH: "skipped (a user-account row holds the same id)",
}


class Command(BaseCommand):
    help = "Add the channels found commenting as themselves under stored posts to the channels list."

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="List the commenting channels with no channel row; no Telegram call, no database write.",
        )

    def handle(self, *args: Any, **options: Any) -> None:
        with styled_warning_logs(self.style):
            self._handle(**options)

    def _handle(self, **options: Any) -> None:
        candidates = unknown_commenting_channels()
        if not candidates:
            self.stdout.write(self.style.SUCCESS("Every channel commenting as itself already has a channel row."))
            return
        if options["dry_run"]:
            self._list(candidates)
            return
        self.stdout.write(f"{len(candidates)} commenting channel(s) without a channel row.")
        with TelegramClient(
            settings.TELEGRAM_SESSION_NAME,
            settings.TELEGRAM_API_ID,
            settings.TELEGRAM_API_HASH,
            connection_retries=settings.TELEGRAM_CONNECTION_RETRIES,
            retry_delay=settings.TELEGRAM_RETRY_DELAY,
            flood_sleep_threshold=settings.TELEGRAM_FLOOD_SLEEP_THRESHOLD,
        ).start(phone=settings.TELEGRAM_PHONE_NUMBER) as client:
            api_client = TelegramAPIClient(client)
            media_handler = MediaHandler(api_client, download_timeout=settings.TELEGRAM_CRAWLER_DOWNLOAD_TIMEOUT)
            crawler = ChannelCrawler(api_client, media_handler, ReferenceResolver(api_client))
            try:
                counts = recover_commenting_channels(crawler, candidates, report=self._report)
            except errors.FloodWaitError as exc:
                self.stdout.write(self.style.WARNING(f"Flood wait ({exc.seconds}s): stopping; run again to continue."))
                if not settings.IGNORE_FLOODWAIT:
                    sleep(settings.TELEGRAM_FLOODWAIT_SLEEP_SECONDS)
                return
        added = sum(n for status, n in counts.items() if status != STATUS_USER_CLASH)
        summary = ", ".join(f"{counts[s]} {s.replace('_', ' ')}" for s in _OUTCOMES if counts.get(s))
        self.stdout.write(self.style.SUCCESS(f"\n{added} channel(s) added to the channels list ({summary})."))

    def _list(self, candidates: list[CommentingChannel]) -> None:
        cache = cached_entities(c.telegram_id for c in candidates)
        self.stdout.write(f"{len(candidates)} commenting channel(s) without a channel row (dry run):\n")
        self.stdout.write(f"{'telegram id':>12}  {'comments':>8}  {'last handle':<24}  name")
        for c in candidates:
            access_hash, username = cache.get(c.telegram_id, (None, ""))
            handle = f"@{username}" if username else ("—" if access_hash else "— (not in session cache)")
            self.stdout.write(f"{c.telegram_id:>12}  {c.comments:>8}  {handle:<24}  {c.name}")

    def _report(self, candidate: CommentingChannel, outcome: str) -> None:
        line = f'"{candidate.name}" [telegram_id={candidate.telegram_id}, {candidate.comments} comments] {_OUTCOMES[outcome]}'
        style = self.style.WARNING if outcome == STATUS_USER_CLASH else self.style.SUCCESS
        self.stdout.write(style(line))
