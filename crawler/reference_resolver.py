import logging
from datetime import datetime, timedelta
from typing import Any

from django.utils import timezone

from crawler.client import TelegramAPIClient
from webapp.models import Channel, Message

from telethon import errors

logger = logging.getLogger(__name__)

SKIPPABLE_REFERENCES = ["joinchat"]


class ReferenceResolver:
    def __init__(self, api_client: TelegramAPIClient) -> None:
        self.api_client = api_client
        self.reference_resolution_paused_until: datetime | None = None

    def _is_paused(self) -> bool:
        return self.reference_resolution_paused_until and timezone.now() < self.reference_resolution_paused_until

    def _pause(self, error: Any) -> int:
        wait_seconds = max(getattr(error, "seconds", 0), 1)
        pause_until = timezone.now() + timedelta(seconds=wait_seconds)
        if not self.reference_resolution_paused_until or pause_until > self.reference_resolution_paused_until:
            self.reference_resolution_paused_until = pause_until
        return wait_seconds

    def _resolve_one(self, reference: str, log_prefix: str = "") -> tuple[Channel | None, bool]:
        """Try to resolve a username to a Channel. Returns (channel_or_None, failed_bool)."""
        channel = Channel.objects.filter(username=reference).first()
        if channel:
            return channel, False

        if self._is_paused():
            return None, True

        try:
            self.api_client.wait()
            new_telegram_channel = self.api_client.client.get_entity(reference)
            return Channel.from_telegram_object(new_telegram_channel, force_update=True), False
        except (ValueError, errors.rpcerrorlist.UsernameInvalidError):
            return None, False
        except errors.rpcerrorlist.FloodWaitError as error:
            wait_seconds = self._pause(error)
            logger.warning(
                "Unable to resolve %sreference '%s' due to flood wait (%ss); skipping for now",
                f"{log_prefix} " if log_prefix else "",
                reference,
                wait_seconds,
            )
            return None, True
        except errors.RPCError as error:
            logger.warning(
                "Unable to resolve %sreference '%s': %s",
                f"{log_prefix} " if log_prefix else "",
                reference,
                error,
            )
            return None, True

    def resolve_message_references(self, message: Message, telegram_message: Any) -> list[str]:
        """Resolve all references in a message. Returns list of unresolved reference strings."""
        missing: list[str] = []

        for reference in message.get_telegram_references():
            reference = reference.strip().lower()
            if reference in SKIPPABLE_REFERENCES:
                continue
            channel, failed = self._resolve_one(reference, log_prefix="message")
            if channel:
                message.references.add(channel)
            elif failed:
                missing.append(reference)

        if telegram_message.entities:
            tme = "https://t.me/"
            for entity in telegram_message.entities:
                if not (hasattr(entity, "url") and entity.url.startswith(tme)):
                    continue
                reference = entity.url[len(tme) :].split("/")[0].strip().lower()
                if reference in SKIPPABLE_REFERENCES:
                    continue
                channel, failed = self._resolve_one(reference, log_prefix="URL")
                if channel:
                    message.references.add(channel)
                elif failed:
                    missing.append(reference)

        return missing

    def get_missing_references(self) -> None:
        for message in Message.objects.exclude(missing_references="").iterator(chunk_size=500):
            all_resolved = True
            for reference in message.missing_references.split("|"):
                if not reference or reference in SKIPPABLE_REFERENCES:
                    continue
                channel, failed = self._resolve_one(reference)
                if channel:
                    message.references.add(channel)
                if failed:
                    all_resolved = False
            if all_resolved:
                message.missing_references = ""
                message.save()
