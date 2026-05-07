import datetime
import logging
from collections.abc import Callable
from time import sleep
from typing import Any

from django.conf import settings
from django.db.models import Max, Min, Q
from django.utils import timezone

from crawler.client import TelegramAPIClient
from crawler.hole_fixer import fix_message_holes
from crawler.media_handler import MediaHandler
from crawler.reference_resolver import ReferenceResolver
from webapp.models import Channel, Message, MessagePicture, MessageReaction, MessageReply, MessageVideo

from telethon import errors, functions
from telethon.tl.functions.channels import GetChannelRecommendationsRequest, GetFullChannelRequest
from telethon.tl.types import InputChannel, MessageService

logger = logging.getLogger(__name__)


def _save_reactions(message_pk: int, telegram_message: Any) -> None:
    """Persist the current emoji reactions for *message_pk* from a Telethon message object.

    Replaces any existing reactions — always reflects the current Telegram state.
    Custom-emoji / sticker reactions are tallied together under the synthetic emoji "custom"
    so that total reaction counts are not understated on channels that use custom emoji packs.
    """
    MessageReaction.objects.filter(message_id=message_pk).delete()
    reactions_obj = getattr(telegram_message, "reactions", None)
    if not reactions_obj:
        return
    to_create = []
    custom_total = 0
    for rc in getattr(reactions_obj, "results", None) or []:
        if hasattr(rc.reaction, "emoticon"):
            to_create.append(MessageReaction(message_id=message_pk, emoji=rc.reaction.emoticon, count=rc.count))
        else:
            custom_total += rc.count
    if custom_total:
        to_create.append(MessageReaction(message_id=message_pk, emoji="custom", count=custom_total))
    if to_create:
        MessageReaction.objects.bulk_create(to_create)


class ChannelCrawler:
    def __init__(
        self,
        api_client: TelegramAPIClient,
        media_handler: MediaHandler,
        reference_resolver: ReferenceResolver,
        messages_limit: int | None = 100,
    ) -> None:
        self.api_client = api_client
        self.media_handler = media_handler
        self.reference_resolver = reference_resolver
        self.messages_limit_per_channel = messages_limit

    def set_more_channel_details(self, channel: Channel, telegram_channel: Any) -> None:
        channel_full_info = self.api_client.client(GetFullChannelRequest(channel=telegram_channel))
        channel.participants_count = channel_full_info.full_chat.participants_count
        channel.about = channel_full_info.full_chat.about
        location = channel_full_info.full_chat.location
        if location:
            channel.telegram_location = getattr(location, "address", "") or str(location)
        channel.is_lost = False
        channel.is_private = False
        full = channel_full_info.full_chat
        rr = getattr(telegram_channel, "restriction_reason", None)
        channel.restriction_reason = (
            [{"platform": r.platform, "reason": r.reason, "text": r.text} for r in rr] if rr else None
        )
        channel.message_ttl = getattr(full, "ttl_period", None) or None
        raw_usernames = getattr(telegram_channel, "usernames", None)
        primary = channel.username.lower() if channel.username else None
        channel.extra_usernames = (
            [u.username for u in raw_usernames if u.active and u.username.lower() != primary] if raw_usernames else None
        ) or None
        linked_chat_id = getattr(full, "linked_chat_id", None) or None
        channel.linked_chat_id = linked_chat_id
        if linked_chat_id and not Channel.objects.filter(telegram_id=linked_chat_id).exists():
            linked_tg = next(
                (c for c in getattr(channel_full_info, "chats", []) if getattr(c, "id", None) == linked_chat_id),
                None,
            )
            if linked_tg is not None:
                try:
                    Channel.from_telegram_object(
                        linked_tg, force_update=False, defaults={"organization": channel.organization}
                    )
                except Exception as exc:
                    logger.warning("Could not create linked channel %s: %s", linked_chat_id, exc)
        channel.available_min_id = getattr(full, "available_min_id", None) or None
        channel.slowmode_seconds = getattr(full, "slowmode_seconds", None) or None
        channel.admins_count = getattr(full, "admins_count", None) or None
        channel.online_count = getattr(full, "online_count", None) or None
        channel.requests_pending = getattr(full, "requests_pending", None) or None
        channel.theme_emoticon = getattr(full, "theme_emoticon", None) or ""
        channel.boosts_applied = getattr(full, "boosts_applied", None) or None
        channel.boosts_unrestrict = getattr(full, "boosts_unrestrict", None) or None
        channel.kicked_count = getattr(full, "kicked_count", None) or None
        channel.banned_count = getattr(full, "banned_count", None) or None
        channel.antispam = bool(getattr(full, "antispam", False))
        channel.has_scheduled = bool(getattr(full, "has_scheduled", False))
        channel.pinned_msg_id = getattr(full, "pinned_msg_id", None) or None
        channel.migrated_from_chat_id = getattr(full, "migrated_from_chat_id", None) or None
        channel.save(
            update_fields=[
                "participants_count",
                "about",
                "telegram_location",
                "is_lost",
                "is_private",
                "restriction_reason",
                "message_ttl",
                "extra_usernames",
                "linked_chat_id",
                "available_min_id",
                "slowmode_seconds",
                "admins_count",
                "online_count",
                "requests_pending",
                "theme_emoticon",
                "boosts_applied",
                "boosts_unrestrict",
                "kicked_count",
                "banned_count",
                "antispam",
                "has_scheduled",
                "pinned_msg_id",
                "migrated_from_chat_id",
            ]
        )

    def resolve_channel_or_classify(self, seed: int | str) -> tuple["Channel | None", Any, str]:
        """Resolve a channel, running all fallbacks before deciding its status.

        Returns (channel, tg_channel, status) where status is one of:
          "ok"           — resolved successfully; channel and tg_channel are set
          "private"      — confirmed inaccessible on every resolution path
          "lost"         — unresolvable / deleted
          "user_account" — seed resolves to a user account, not a channel

        FloodWaitError is always propagated to the caller.
        """
        try:
            channel, tg_ch = self.get_basic_channel(seed)
            if channel is not None:
                return channel, tg_ch, "ok"
            # get_basic_channel returned (None, None) without raising → invalid ID
            return None, None, "lost"
        except (errors.rpcerrorlist.ChannelPrivateError, ValueError) as exc:
            initial_private = isinstance(exc, errors.rpcerrorlist.ChannelPrivateError)

        # ── Fallback chain ────────────────────────────────────────────────────
        # ChannelPrivateError from a bare numeric lookup is ambiguous: Telegram
        # returns it for both genuinely private channels and deleted ones.
        # ValueError means Telethon lacks a cached access_hash.
        # Try access_hash then username before concluding.
        is_private = initial_private

        if isinstance(seed, int):
            db_ch = Channel.objects.filter(telegram_id=seed).only("username", "access_hash").first()

            if db_ch and db_ch.access_hash:
                try:
                    channel, tg_ch = self.get_basic_channel(
                        InputChannel(channel_id=seed, access_hash=db_ch.access_hash)
                    )
                    if channel is not None:
                        return channel, tg_ch, "ok"
                    is_private = False
                except errors.rpcerrorlist.ChannelPrivateError:
                    is_private = True
                except (ValueError, errors.rpcerrorlist.ChannelInvalidError):
                    is_private = False  # stale hash — still try username

            if db_ch and db_ch.username:
                try:
                    channel, tg_ch = self.get_basic_channel(db_ch.username)
                    if channel is not None:
                        return channel, tg_ch, "ok"
                    is_private = False
                except errors.rpcerrorlist.ChannelPrivateError:
                    is_private = True
                except (ValueError, errors.rpcerrorlist.ChannelInvalidError):
                    is_private = False  # username also unresolvable → lost

        if is_private:
            return None, None, "private"
        if initial_private:
            return None, None, "lost"
        return None, None, "user_account"

    def get_basic_channel(self, seed: int | str) -> tuple[Channel, Any] | tuple[None, None]:
        self.api_client.wait()
        try:
            telegram_channel = self.api_client.client.get_entity(seed)
            return (
                (Channel.from_telegram_object(telegram_channel, force_update=True), telegram_channel)
                if telegram_channel
                else (None, None)
            )
        except (errors.rpcerrorlist.ChannelInvalidError, errors.rpcerrorlist.UsernameInvalidError):
            logger.info("Not available seed: %s", seed)
            return None, None
        # ChannelPrivateError propagates so resolve_channel_or_classify() can distinguish it from "not found"

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

        channel, telegram_channel, status = self.resolve_channel_or_classify(seed)
        if status == "private":
            Channel.objects.filter(Q(telegram_id=seed) | Q(username=seed)).update(is_private=True, is_lost=False)
            update_status(f"[telegram_id={seed}] | skipped (channel is private)")
            return 0
        if status == "lost":
            Channel.objects.filter(Q(telegram_id=seed) | Q(username=seed)).update(is_lost=True, is_private=False)
            update_status(f"[telegram_id={seed}] | skipped (channel not found)")
            return 0
        if status == "user_account":
            logger.info("Seed is a user account not resolvable by username: %s", seed)
            Channel.objects.filter(Q(telegram_id=seed) | Q(username=seed)).update(is_user_account=True, is_lost=False)
            update_status(f"[telegram_id={seed}] | skipped (user account)")
            return 0

        channel_label = f"[id={channel.id}] {channel}"
        update_status(f"{channel_label} | fetching profile pictures")
        image_count = self.media_handler.download_profile_picture(telegram_channel)

        update_status(f"{channel_label} | fetching channel details")
        self.set_more_channel_details(channel, telegram_channel)

        id_agg = channel.message_set.aggregate(min_id=Min("telegram_id"), max_id=Max("telegram_id"))
        last_known_id = id_agg["max_id"] or 0
        message_count = 0
        if self.messages_limit_per_channel is None or self.messages_limit_per_channel <= 0:
            remaining_limit: int | None = None
        else:
            remaining_limit = self.messages_limit_per_channel
        update_status(f"{channel_label} | downloading recent messages")
        batch_count = 0
        for telegram_message in self.api_client.client.iter_messages(
            telegram_channel,
            min_id=last_known_id,
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
                self._resolve_pending_forwards(status_callback)
                channel.are_messages_crawled = True
                channel.is_lost = False
                channel.is_private = False
                channel.save()
                update_status(
                    f"{channel_label} | completed ({message_count} new messages, {image_count} downloaded images)"
                )
                return last_known_id

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
                self._resolve_pending_forwards(status_callback)
                channel.are_messages_crawled = True
                channel.is_lost = False
                channel.is_private = False
                channel.save()
                update_status(
                    f"{channel_label} | completed ({message_count} new messages, {image_count} downloaded images)"
                )
                return last_known_id

        if fix_holes:
            update_status(f"{channel_label} | checking for message holes")
            hole_message_count, hole_image_count = fix_message_holes(
                channel,
                telegram_channel,
                self.api_client,
                self.get_message,
                remaining_limit,
                update_status,
                channel_label,
                message_count,
            )
            message_count += hole_message_count
            image_count += hole_image_count

        self._resolve_pending_forwards(status_callback)
        channel.are_messages_crawled = True
        channel.is_lost = False
        channel.is_private = False
        channel.save()
        update_status(f"{channel_label} | completed ({message_count} new messages, {image_count} downloaded images)")
        return last_known_id

    def get_message(self, channel: Channel, telegram_message: Any) -> int:
        if isinstance(telegram_message, MessageService):
            return 0
        if (
            channel.uninteresting_after
            and telegram_message.date
            and telegram_message.date.date() > channel.uninteresting_after
        ):
            return 0
        downloaded_images = 0
        message = Message.from_telegram_object(telegram_message, force_update=True, defaults={"channel": channel})

        if telegram_message.fwd_from:
            message.fwd_from_channel_post = getattr(telegram_message.fwd_from, "channel_post", None)
            message.fwd_from_from_name = getattr(telegram_message.fwd_from, "from_name", None) or ""

        if (
            telegram_message.fwd_from
            and telegram_message.fwd_from.from_id
            and hasattr(telegram_message.fwd_from.from_id, "channel_id")
        ):
            channel_id = telegram_message.fwd_from.from_id.channel_id
            existing = Channel.objects.filter(telegram_id=channel_id).first()
            if existing:
                # Persist immediately so a crash before message.save() doesn't lose the edge.
                # Also clear any stale pending_forward_telegram_id from a previous partial run.
                Message.objects.filter(pk=message.pk).update(forwarded_from=existing, pending_forward_telegram_id=None)
                message.forwarded_from = existing
                message.pending_forward_telegram_id = None
            else:
                # Defer the get_entity() call to _resolve_pending_forwards() so that
                # a channel with many novel forwards doesn't burst the API mid-iteration.
                # Persisted to DB immediately so a crash doesn't lose the pending lookup.
                Message.objects.filter(pk=message.pk).update(pending_forward_telegram_id=channel_id)
                message.pending_forward_telegram_id = channel_id

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

        replies_obj = getattr(telegram_message, "replies", None)
        message.replies = getattr(replies_obj, "replies", None)

        reply_to = getattr(telegram_message, "reply_to", None)
        message.reply_to_msg_id = getattr(reply_to, "reply_to_msg_id", None)

        fc = getattr(telegram_message, "factcheck", None)
        if fc is not None:
            text_obj = getattr(fc, "text", None)
            message.factcheck = {
                "need_check": bool(getattr(fc, "need_check", False)),
                "country": getattr(fc, "country", None),
                "text": getattr(text_obj, "text", None) if text_obj else None,
            }

        message.save()
        _save_reactions(message.pk, telegram_message)
        return downloaded_images

    def _resolve_pending_forwards(self, status_callback: Callable[[str], None] | None = None) -> None:
        """Resolve forwarded-channel entity lookups deferred during get_message().

        Reads all messages with pending_forward_telegram_id set (persisted to DB by
        get_message() so that a hard crash does not lose the work).  Resolves each
        unique channel with a full api_client.wait() between calls.  On FloodWaitError
        the loop stops early; unresolved rows keep pending_forward_telegram_id set and
        are retried automatically on the next get_channel() call.
        """
        pending_ids = list(
            Message.objects.filter(pending_forward_telegram_id__isnull=False)
            .values_list("pending_forward_telegram_id", flat=True)
            .distinct()
        )
        if not pending_ids:
            return
        total = len(pending_ids)
        for index, channel_id in enumerate(pending_ids, 1):
            if status_callback:
                status_callback(f"resolving forwarded channels … {index}/{total}")
            self.api_client.wait()
            try:
                telegram_channel = self.api_client.client.get_entity(channel_id)
                resolved = Channel.from_telegram_object(telegram_channel, force_update=True)
                Message.objects.filter(pending_forward_telegram_id=channel_id).update(
                    forwarded_from=resolved,
                    pending_forward_telegram_id=None,
                )
            except errors.rpcerrorlist.FloodWaitError:
                logger.warning("Flood wait during forwarded-channel resolution; %d entries skipped", total - index + 1)
                if not settings.IGNORE_FLOODWAIT:
                    sleep(settings.TELEGRAM_FLOODWAIT_SLEEP_SECONDS)
                break
            except errors.rpcerrorlist.ChannelPrivateError:
                Message.objects.filter(pending_forward_telegram_id=channel_id).update(
                    forwarded_from_private=channel_id,
                    pending_forward_telegram_id=None,
                )
            except (AttributeError, ValueError):
                Message.objects.filter(pending_forward_telegram_id=channel_id).update(
                    forwarded_from_private=0,
                    pending_forward_telegram_id=None,
                )

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

        Channel.objects.filter(pk=channel.pk).update(is_lost=False, is_private=False)
        now = timezone.now()
        # Convert date to a timezone-aware datetime for comparison with message dates.
        cutoff: datetime.datetime | None = (
            datetime.datetime(min_date.year, min_date.month, min_date.day, tzinfo=datetime.timezone.utc)
            if min_date is not None
            else None
        )
        # When max_telegram_id is set, pass it as max_id to iter_messages so that newly-crawled
        # messages don't consume the limit before we reach the messages we actually want to refresh.
        # Telethon's max_id is exclusive (id < max_id), so add 1 to include max_telegram_id itself.
        iter_max_id = (max_telegram_id + 1) if (max_telegram_id is not None and max_telegram_id > 0) else 0
        updated = 0
        for telegram_message in self.api_client.client.iter_messages(
            telegram_channel,
            limit=limit,
            wait_time=self.api_client.wait_time,
            max_id=iter_max_id,
        ):
            if cutoff is not None and telegram_message.date is not None and telegram_message.date < cutoff:
                break
            if (
                channel.uninteresting_after
                and telegram_message.date is not None
                and telegram_message.date.date() > channel.uninteresting_after
            ):
                continue
            if isinstance(telegram_message, MessageService):
                Message.objects.filter(channel=channel, telegram_id=telegram_message.id).delete()
                continue
            replies_obj = getattr(telegram_message, "replies", None)
            media = telegram_message.media
            webpage = getattr(media, "webpage", None) if media else None
            fc = getattr(telegram_message, "factcheck", None)
            if fc is not None:
                text_obj = getattr(fc, "text", None)
                factcheck_data = {
                    "need_check": bool(getattr(fc, "need_check", False)),
                    "country": getattr(fc, "country", None),
                    "text": getattr(text_obj, "text", None) if text_obj else None,
                }
            else:
                factcheck_data = None
            update_kwargs: dict = {
                "views": telegram_message.views,
                "forwards": telegram_message.forwards,
                "replies": getattr(replies_obj, "replies", None),
                "pinned": bool(telegram_message.pinned),
                "edit_date": telegram_message.edit_date,
                "post_author": telegram_message.post_author or "",
                "message": telegram_message.message or "",
                "webpage_url": getattr(webpage, "url", "") or "",
                "webpage_type": getattr(webpage, "type", "") or "",
                "factcheck": factcheck_data,
                "_updated": now,
            }
            if telegram_message.pinned:
                update_kwargs["has_been_pinned"] = True
            rows = Message.objects.filter(
                channel=channel,
                telegram_id=telegram_message.id,
            ).update(**update_kwargs)
            if rows:
                updated += 1
                msg_pk = (
                    Message.objects.filter(channel=channel, telegram_id=telegram_message.id)
                    .values_list("pk", flat=True)
                    .first()
                )
                if msg_pk is not None:
                    _save_reactions(msg_pk, telegram_message)
                if telegram_message.media:
                    if (
                        hasattr(telegram_message.media, "photo")
                        and not MessagePicture.objects.filter(
                            message__channel=channel, message__telegram_id=telegram_message.id
                        ).exists()
                    ):
                        self.media_handler.download_message_picture(telegram_message)
                    if not MessageVideo.objects.filter(
                        message__channel=channel, message__telegram_id=telegram_message.id
                    ).exists():
                        self.media_handler.download_message_video(telegram_message)
            update_status(f"refreshing message stats … {updated} updated")
        return updated

    def get_recommended_channels(self, channel: Channel) -> tuple[int, int]:
        """Fetch Telegram-recommended channels for *channel*. Returns (total_found, new_to_db)."""
        if not channel.access_hash:
            return 0, 0
        self.api_client.wait()
        try:
            result = self.api_client.client(
                GetChannelRecommendationsRequest(
                    channel=InputChannel(channel_id=channel.telegram_id, access_hash=channel.access_hash)
                )
            )
        except errors.FloodWaitError:
            raise
        except Exception:
            return 0, 0
        total = 0
        new = 0
        for chat in result.chats:
            if not hasattr(chat, "id"):
                continue
            total += 1
            if not Channel.objects.filter(telegram_id=chat.id).exists():
                Channel.from_telegram_object(chat, force_update=True)
                new += 1
        return total, new

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

    def fetch_channel_replies(
        self,
        channel: Channel,
        status_callback: Callable[[str], None] | None = None,
    ) -> int:
        """Fetch and upsert reply messages for all posts in *channel* with replies > 0.

        Replies live in the linked discussion group (channel.linked_chat_id). Returns the
        number of MessageReply records created or updated.
        """
        if not channel.linked_chat_id:
            return 0

        self.api_client.wait()
        try:
            linked_entity = self.api_client.client.get_entity(channel.linked_chat_id)
        except errors.rpcerrorlist.ChannelPrivateError:
            logger.warning("Linked group %s for %s is private; skipping replies.", channel.linked_chat_id, channel)
            return 0
        except errors.FloodWaitError:
            raise
        except Exception as exc:
            logger.warning("Could not resolve linked group %s for %s: %s", channel.linked_chat_id, channel, exc)
            return 0

        parent_messages = list(Message.objects.filter(channel=channel, replies__gt=0).values_list("pk", "telegram_id"))
        if not parent_messages:
            return 0

        total_upserted = 0
        for msg_pk, msg_telegram_id in parent_messages:
            if status_callback:
                status_callback(f"[id={channel.id}] {channel} | replies for post #{msg_telegram_id}")
            self.api_client.wait()
            try:
                to_upsert: list[MessageReply] = []
                for tg_reply in self.api_client.client.iter_messages(linked_entity, reply_to=msg_telegram_id):
                    if isinstance(tg_reply, MessageService):
                        continue
                    sender_name = ""
                    if getattr(tg_reply, "post_author", None):
                        sender_name = tg_reply.post_author
                    elif tg_reply.sender:
                        first = getattr(tg_reply.sender, "first_name", "") or ""
                        last = getattr(tg_reply.sender, "last_name", "") or ""
                        uname = getattr(tg_reply.sender, "username", "") or ""
                        sender_name = f"{first} {last}".strip() or uname
                    to_upsert.append(
                        MessageReply(
                            parent_message_id=msg_pk,
                            telegram_id=tg_reply.id,
                            date=tg_reply.date,
                            text=tg_reply.message or "",
                            sender_name=sender_name[:255],
                            sender_id=tg_reply.sender_id,
                            views=getattr(tg_reply, "views", None),
                        )
                    )
                if to_upsert:
                    MessageReply.objects.bulk_create(
                        to_upsert,
                        update_conflicts=True,
                        unique_fields=["parent_message", "telegram_id"],
                        update_fields=["date", "text", "sender_name", "sender_id", "views"],
                    )
                    total_upserted += len(to_upsert)
            except errors.FloodWaitError:
                raise
            except errors.rpcerrorlist.ChannelPrivateError:
                logger.warning("ChannelPrivateError fetching replies for post %s in %s", msg_telegram_id, channel)
            except Exception as exc:
                logger.warning("Error fetching replies for post %s in %s: %s", msg_telegram_id, channel, exc)

        return total_upserted

    def get_missing_references(self, status_callback=None, force_retry: bool = False, channel_qs=None) -> None:
        self.reference_resolver.get_missing_references(
            status_callback=status_callback, force_retry=force_retry, channel_qs=channel_qs
        )
