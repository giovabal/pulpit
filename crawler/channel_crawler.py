import datetime
import logging
from collections.abc import Callable
from typing import Any

from django.conf import settings
from django.db.models import Max, Min, Q
from django.utils import timezone

from crawler.client import TelegramAPIClient
from crawler.media_handler import MediaHandler
from crawler.reference_resolver import ReferenceResolver
from webapp.models import Channel, Message

from telethon import errors, functions
from telethon.tl.functions.channels import GetFullChannelRequest
from telethon.tl.types import MessageService

logger = logging.getLogger(__name__)

_HOLE_FETCH_BATCH_SIZE: int = 100


class ChannelCrawler:
    def __init__(
        self, api_client: TelegramAPIClient, media_handler: MediaHandler, reference_resolver: ReferenceResolver
    ) -> None:
        self.api_client = api_client
        self.media_handler = media_handler
        self.reference_resolver = reference_resolver
        self.messages_limit_per_channel: int | None = settings.TELEGRAM_CRAWLER_MESSAGES_LIMIT_PER_CHANNEL

    def set_more_channel_details(self, channel: Channel, telegram_channel: Any) -> None:
        channel_full_info = self.api_client.client(GetFullChannelRequest(channel=telegram_channel))
        channel.participants_count = channel_full_info.full_chat.participants_count
        channel.about = channel_full_info.full_chat.about
        location = channel_full_info.full_chat.location
        if location:
            channel.telegram_location = getattr(location, "address", "") or str(location)
        channel.save(update_fields=["participants_count", "about"])

    def get_basic_channel(self, seed: int | str) -> tuple[Channel, Any] | tuple[None, None]:
        self.api_client.wait()
        try:
            telegram_channel = self.api_client.client.get_entity(seed)
            return (
                (Channel.from_telegram_object(telegram_channel, force_update=True), telegram_channel)
                if telegram_channel
                else (None, None)
            )
        except errors.rpcerrorlist.ChannelPrivateError:
            logger.info("Not available seed: %s", seed)
            return None, None

    def get_channel(
        self,
        seed: int | str,
        status_callback: Callable[[str], None] | None = None,
        fix_holes: bool = False,
    ) -> int:
        """Crawl a channel and return the pre-crawl max telegram_id (0 if none existed)."""

        def update_status(message: str) -> None:
            if status_callback:
                status_callback(message)

        try:
            channel, telegram_channel = self.get_basic_channel(seed)
        except ValueError:
            logger.info("Seed is a user account, not a channel: %s", seed)
            Channel.objects.filter(Q(telegram_id=seed) | Q(username=seed)).update(is_user_account=True)
            return 0
        if channel is None:
            Channel.objects.filter(Q(telegram_id=seed) | Q(username=seed)).update(is_lost=True)
            return 0

        channel_label = f"[id={channel.id}] {channel}"
        update_status(f"{channel_label} | fetching profile pictures")
        image_count = self.media_handler.download_profile_picture(telegram_channel)

        update_status(f"{channel_label} | fetching channel details")
        self.set_more_channel_details(channel, telegram_channel)

        id_agg = channel.message_set.aggregate(min_id=Min("telegram_id"), max_id=Max("telegram_id"))
        min_id = id_agg["max_id"] or 0
        message_count = 0
        if self.messages_limit_per_channel is None or self.messages_limit_per_channel <= 0:
            remaining_limit: int | None = None
        else:
            remaining_limit = self.messages_limit_per_channel
        update_status(f"{channel_label} | downloading recent messages")
        batch_count = 0
        for telegram_message in self.api_client.client.iter_messages(
            telegram_channel,
            min_id=min_id,
            wait_time=self.api_client.wait_time,
            limit=remaining_limit,
            reverse=True,
        ):
            batch_count += 1
            image_count += self.get_message(channel, telegram_message)
            update_status(f"{channel_label} | messages processed: {message_count + batch_count}")

        message_count += batch_count
        if remaining_limit is not None:
            remaining_limit -= batch_count
            if remaining_limit <= 0:
                channel.are_messages_crawled = True
                channel.is_lost = False
                channel.save()
                update_status(
                    f"{channel_label} | completed ({message_count} new messages, {image_count} downloaded images)"
                )
                return min_id

        max_id = id_agg["min_id"] if not channel.are_messages_crawled else None

        batch_count = 0
        if max_id is not None:
            update_status(f"{channel_label} | downloading history")
            for telegram_message in self.api_client.client.iter_messages(
                telegram_channel, max_id=max_id, wait_time=self.api_client.wait_time, limit=remaining_limit
            ):
                batch_count += 1
                image_count += self.get_message(channel, telegram_message)
                update_status(f"{channel_label} | messages processed: {message_count + batch_count}")

        message_count += batch_count
        if remaining_limit is not None:
            remaining_limit -= batch_count
            if remaining_limit <= 0:
                channel.are_messages_crawled = True
                channel.is_lost = False
                channel.save()
                update_status(
                    f"{channel_label} | completed ({message_count} new messages, {image_count} downloaded images)"
                )
                return

        if fix_holes:
            update_status(f"{channel_label} | checking for message holes")
            hole_message_count, hole_image_count = self._fix_message_holes(
                channel, telegram_channel, remaining_limit, update_status, channel_label, message_count
            )
            message_count += hole_message_count
            image_count += hole_image_count

        channel.are_messages_crawled = True
        channel.is_lost = False
        channel.save()
        update_status(f"{channel_label} | completed ({message_count} new messages, {image_count} downloaded images)")
        return min_id

    def _find_missing_message_ids(self, channel: Channel, min_telegram_id: int | None = None) -> list[int]:
        messages = channel.message_set.order_by("telegram_id")
        if min_telegram_id is not None:
            messages = messages.filter(telegram_id__gte=min_telegram_id)
        holes: list[int] = []
        prev_id: int | None = None
        for (current_id,) in messages.values_list("telegram_id").iterator():
            if prev_id is not None and current_id - prev_id > 1:
                holes.extend(range(prev_id + 1, current_id))
            prev_id = current_id
        return holes

    def _fix_message_holes(
        self,
        channel: Channel,
        telegram_channel: Any,
        remaining_limit: int | None,
        update_status: Callable[[str], None],
        channel_label: str,
        current_message_count: int,
    ) -> tuple[int, int]:
        baseline_min_id = channel.last_hole_check_max_telegram_id
        missing_ids = self._find_missing_message_ids(channel, min_telegram_id=baseline_min_id)
        if not missing_ids:
            channel.last_hole_check_max_telegram_id = channel.message_set.aggregate(Max("telegram_id"))[
                "telegram_id__max"
            ]
            channel.save(update_fields=["last_hole_check_max_telegram_id"])
            update_status(f"{channel_label} | no message holes found")
            return 0, 0

        processed_messages = 0
        downloaded_images = 0
        was_limited = False
        if remaining_limit is not None and remaining_limit > 0:
            was_limited = len(missing_ids) > remaining_limit
            missing_ids = missing_ids[:remaining_limit]

        update_status(f"{channel_label} | fixing {len(missing_ids)} missing message ids")

        for offset in range(0, len(missing_ids), _HOLE_FETCH_BATCH_SIZE):
            batch = missing_ids[offset : offset + _HOLE_FETCH_BATCH_SIZE]
            self.api_client.wait()
            messages = self.api_client.client.get_messages(telegram_channel, ids=batch)
            if not isinstance(messages, list):
                messages = [messages]
            for telegram_message in messages:
                if telegram_message is None or not hasattr(telegram_message, "peer_id"):
                    continue
                downloaded_images += self.get_message(channel, telegram_message)
                processed_messages += 1
                update_status(f"{channel_label} | messages processed: {current_message_count + processed_messages}")
            # Save progress after each batch so an interrupted run resumes from here
            channel.last_hole_check_max_telegram_id = batch[-1]
            channel.save(update_fields=["last_hole_check_max_telegram_id"])

        if was_limited:
            update_status(f"{channel_label} | hole-fix limit reached, checkpoint saved")
            return processed_messages, downloaded_images

        channel.last_hole_check_max_telegram_id = channel.message_set.aggregate(Max("telegram_id"))["telegram_id__max"]
        channel.save(update_fields=["last_hole_check_max_telegram_id"])
        return processed_messages, downloaded_images

    def get_message(self, channel: Channel, telegram_message: Any) -> int:
        if isinstance(telegram_message, MessageService):
            return 0
        downloaded_images = 0
        message = Message.from_telegram_object(telegram_message, force_update=True, defaults={"channel": channel})

        if (
            telegram_message.fwd_from
            and telegram_message.fwd_from.from_id
            and hasattr(telegram_message.fwd_from.from_id, "channel_id")
        ):
            channel_id = telegram_message.fwd_from.from_id.channel_id
            existing = Channel.objects.filter(telegram_id=channel_id).first()
            if existing:
                message.forwarded_from = existing
            else:
                try:
                    self.api_client.wait()
                    new_telegram_channel = self.api_client.client.get_entity(channel_id)
                    message.forwarded_from = Channel.from_telegram_object(new_telegram_channel, force_update=True)
                except errors.rpcerrorlist.ChannelPrivateError:
                    message.forwarded_from_private = channel_id
                except (AttributeError, ValueError):
                    message.forwarded_from_private = 0

        missing_references = self.reference_resolver.resolve_message_references(message, telegram_message)
        if missing_references:
            message.missing_references = "|".join(missing_references)

        if telegram_message.media:
            downloaded_images += self.media_handler.download_message_picture(telegram_message)
            self.media_handler.download_message_video(telegram_message)
            if hasattr(telegram_message.media, "photo"):
                message.media_type = "photo"
            elif hasattr(telegram_message.media, "document"):
                doc = telegram_message.media.document
                mime_type = getattr(doc, "mime_type", "") or ""
                if mime_type.startswith("video/"):
                    message.media_type = "video"
                elif mime_type.startswith("audio/"):
                    message.media_type = "audio"
                else:
                    message.media_type = "document"
            if hasattr(telegram_message.media, "webpage"):
                message.webpage_url = (
                    telegram_message.media.webpage.url if hasattr(telegram_message.media.webpage, "url") else ""
                )
                message.webpage_type = (
                    telegram_message.media.webpage.type if hasattr(telegram_message.media.webpage, "type") else ""
                )

        message.save()
        return downloaded_images

    def refresh_message_stats(
        self,
        channel: Channel,
        telegram_channel: Any,
        limit: int | None = None,
        min_date: datetime.date | None = None,
        max_telegram_id: int | None = None,
        status_callback: Callable[[str], None] | None = None,
    ) -> int:
        """Re-fetch messages and update views/forwards/pinned in place.

        ``limit=None`` and ``min_date=None`` refreshes all stored messages.
        ``limit=N`` restricts the refresh to the N most recent messages.
        ``min_date`` refreshes all messages whose date is on or after that date;
        iteration stops as soon as an older message is encountered.
        ``max_telegram_id``, when set, skips messages whose telegram id is above
        this value — used to exclude messages freshly stored in the same crawl run.
        ``_updated`` is explicitly stamped because QuerySet.update() bypasses
        the auto_now behaviour of that field.
        """

        def update_status(message: str) -> None:
            if status_callback:
                status_callback(message)

        now = timezone.now()
        # Convert date to a timezone-aware datetime for comparison with message dates.
        cutoff: datetime.datetime | None = (
            datetime.datetime(min_date.year, min_date.month, min_date.day, tzinfo=datetime.timezone.utc)
            if min_date is not None
            else None
        )
        updated = 0
        for telegram_message in self.api_client.client.iter_messages(
            telegram_channel,
            limit=limit,
            wait_time=self.api_client.wait_time,
        ):
            if max_telegram_id is not None and telegram_message.id > max_telegram_id:
                continue
            if cutoff is not None and telegram_message.date is not None and telegram_message.date < cutoff:
                break
            if isinstance(telegram_message, MessageService):
                Message.objects.filter(channel=channel, telegram_id=telegram_message.id).delete()
                continue
            rows = Message.objects.filter(
                channel=channel,
                telegram_id=telegram_message.id,
            ).update(
                views=telegram_message.views,
                forwards=telegram_message.forwards,
                pinned=bool(telegram_message.pinned),
                _updated=now,
            )
            if rows:
                updated += 1
            update_status(f"refreshing message stats … {updated} updated")
        return updated

    def search_channel(self, q: str, limit: int = 1000) -> tuple[int, int]:
        """Search for channels matching q. Returns (total_found, new_to_db)."""
        self.api_client.wait()
        results_count = 0
        new_count = 0
        result = self.api_client.client(functions.contacts.SearchRequest(q=q, limit=limit))
        for channel in result.chats:
            if hasattr(channel, "id"):
                results_count += 1
                if not Channel.objects.filter(telegram_id=channel.id).exists():
                    Channel.from_telegram_object(channel, force_update=True)
                    new_count += 1
        return results_count, new_count

    def get_missing_references(self) -> None:
        self.reference_resolver.get_missing_references()
