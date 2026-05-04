import logging
from collections.abc import Callable
from datetime import datetime, timedelta
from typing import Any

from django.utils import timezone

from crawler.client import TelegramAPIClient
from webapp.models import Channel, Message

from telethon import errors

logger = logging.getLogger(__name__)

# "joinchat" is a Telegram invite-link prefix (t.me/joinchat/<code>), not a real channel username.
SKIPPABLE_REFERENCES = {"joinchat"}

# Prefix stored in missing_references to mark a reference as permanently unresolvable.
# Prefixed entries are skipped on subsequent retries unless force_retry=True.
DEAD_PREFIX = "!"


class ReferenceResolver:
    def __init__(self, api_client: TelegramAPIClient) -> None:
        self.api_client = api_client
        self.reference_resolution_paused_until: datetime | None = None

    def _is_paused(self) -> bool:
        return bool(self.reference_resolution_paused_until and timezone.now() < self.reference_resolution_paused_until)

    def _pause(self, error: Any) -> int:
        wait_seconds = max(getattr(error, "seconds", 0), 1)
        pause_until = timezone.now() + timedelta(seconds=wait_seconds)
        if not self.reference_resolution_paused_until or pause_until > self.reference_resolution_paused_until:
            self.reference_resolution_paused_until = pause_until
        return wait_seconds

    def _resolve_one(self, reference: str, log_prefix: str = "") -> tuple[Channel | None, bool]:
        """Try to resolve a username to a Channel.

        Returns (channel, should_retry) where:
          - (channel, False) — resolved successfully
          - (None, True)     — temporary failure (flood wait, RPC error, paused); retry later
          - (None, False)    — permanent failure (username invalid or not found); do not retry
        """
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
            # Permanent: username does not exist or is invalid — no point retrying
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
            # Transient RPC error — keep for retry
            logger.warning(
                "Unable to resolve %sreference '%s': %s",
                f"{log_prefix} " if log_prefix else "",
                reference,
                error,
            )
            return None, True

    def resolve_message_references(self, message: Message, telegram_message: Any) -> list[str]:
        """Resolve all references in a message. Returns list of unresolved reference strings."""
        refs: set[str] = set()

        for reference in message.get_telegram_references():
            ref = reference.strip().lower()
            if ref and ref not in SKIPPABLE_REFERENCES:
                refs.add(ref)

        if telegram_message.entities:
            tme = "https://t.me/"
            for entity in telegram_message.entities:
                if not (hasattr(entity, "url") and entity.url and entity.url.startswith(tme)):
                    continue
                ref = entity.url[len(tme) :].split("/")[0].strip().lower()
                if ref and ref not in SKIPPABLE_REFERENCES:
                    refs.add(ref)

        missing: list[str] = []
        for reference in refs:
            channel, should_retry = self._resolve_one(reference)
            if channel:
                message.references.add(channel)
            elif should_retry:
                missing.append(reference)

        return missing

    def get_missing_references(
        self,
        status_callback: Callable[[str], None] | None = None,
        force_retry: bool = False,
        channel_qs=None,
    ) -> None:
        qs = Message.objects.exclude(missing_references="")
        if channel_qs is not None:
            qs = qs.filter(channel__in=channel_qs)
        total = qs.count() if status_callback is not None else 0
        to_update: list[Message] = []
        to_add: list[tuple[Message, "Channel"]] = []
        for index, message in enumerate(qs.iterator(chunk_size=500), start=1):
            remaining: list[str] = []
            for raw in message.missing_references.split("|"):
                if not raw:
                    continue
                is_dead = raw.startswith(DEAD_PREFIX)
                reference = raw[len(DEAD_PREFIX) :] if is_dead else raw
                if reference in SKIPPABLE_REFERENCES:
                    continue
                if is_dead and not force_retry:
                    remaining.append(raw)
                    continue
                channel, should_retry = self._resolve_one(reference)
                if channel:
                    to_add.append((message, channel))  # deferred until after bulk_update
                elif should_retry:
                    remaining.append(reference)  # transient failure — keep for retry
                else:
                    remaining.append(DEAD_PREFIX + reference)  # permanent failure — mark dead
            new_value = "|".join(remaining)
            if new_value != message.missing_references:
                message.missing_references = new_value
                to_update.append(message)
            if len(to_update) >= 500:
                Message.objects.bulk_update(to_update, ["missing_references"])
                to_update.clear()
                for msg, ch in to_add:
                    msg.references.add(ch)
                to_add.clear()
            if status_callback is not None:
                status_callback(f"{index}/{total}")
        if to_update:
            Message.objects.bulk_update(to_update, ["missing_references"])
        for msg, ch in to_add:
            msg.references.add(ch)
