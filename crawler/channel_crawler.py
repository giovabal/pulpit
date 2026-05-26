import datetime
import logging
from collections.abc import Callable
from time import sleep
from typing import Any

from django.conf import settings
from django.db import DatabaseError
from django.db.models import Max, Min, Q
from django.utils import timezone

from crawler.client import TelegramAPIClient
from crawler.hole_fixer import fix_message_holes
from crawler.media_handler import MediaHandler
from crawler.reference_resolver import ReferenceResolver
from webapp.models import (
    Channel,
    Message,
    MessageReaction,
    MessageReply,
    Poll,
    PollAnswer,
)

from telethon import errors, functions
from telethon.tl.functions.channels import GetChannelRecommendationsRequest, GetFullChannelRequest
from telethon.tl.types import InputChannel, MessageService, PeerChannel, User

logger = logging.getLogger(__name__)


class _UserAccountSeed(Exception):
    """Sentinel raised by get_basic_channel when the seed resolves to a Telegram User."""


def _save_reactions(message_pk: int, telegram_message: Any) -> None:
    """Persist the current emoji reactions for *message_pk* from a Telethon message object.

    Replaces any existing reactions — always reflects the current Telegram state.
    Custom-emoji / sticker reactions are tallied together under the synthetic emoji "custom"
    so that total reaction counts are not understated on channels that use custom emoji packs.
    """
    MessageReaction.objects.filter(message_id=message_pk).delete()
    to_create: list[MessageReaction] = []
    reactions_obj = getattr(telegram_message, "reactions", None)
    if reactions_obj:
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
    # Keep Message.total_reactions in sync — including the N → 0 case, so the
    # denormalised sort key never goes stale.
    Message.objects.filter(pk=message_pk).update(total_reactions=sum(r.count for r in to_create))


def _save_poll(message_pk: int, telegram_message: Any) -> None:
    media = telegram_message.media
    if not hasattr(media, "poll"):
        return
    tg_poll = media.poll
    tg_results = getattr(media, "results", None)
    poll, _ = Poll.objects.update_or_create(
        message_id=message_pk,
        defaults={
            "poll_id": tg_poll.id,
            "question": tg_poll.question.text,
            "closed": bool(tg_poll.closed),
            "public_voters": bool(tg_poll.public_voters),
            "multiple_choice": bool(tg_poll.multiple_choice),
            "quiz": bool(tg_poll.quiz),
            "close_date": getattr(tg_poll, "close_date", None),
            "total_voters": getattr(tg_results, "total_voters", None),
            "solution": getattr(tg_results, "solution", None) or "",
        },
    )
    result_map: dict[bytes, tuple[int, bool | None]] = {}
    for r in getattr(tg_results, "results", None) or []:
        result_map[bytes(r.option)] = (r.voters, getattr(r, "correct", None))
    for answer in tg_poll.answers:
        option_bytes = bytes(answer.option)
        voters, correct = result_map.get(option_bytes, (0, None))
        PollAnswer.objects.update_or_create(
            poll=poll,
            option=option_bytes,
            defaults={"text": answer.text.text, "voters": voters, "correct": correct},
        )


def _build_msg_update_kwargs(telegram_message: Any, now: datetime.datetime) -> dict:
    """Build the volatile-stats update dict used to refresh a stored Message row.

    Content fields (``message``, ``post_author``, ``webpage_url``, ``webpage_type``,
    ``media_type``) are deliberately omitted: when a channel is restricted or banned,
    Telegram replaces real post content with a stub such as
    *"This channel can't be displayed because it violated Telegram's Terms of Service"*,
    and an older policy of "refresh everything" would silently overwrite the original
    text we captured at first crawl. The first-crawl record is treated as the canonical
    copy; only fields that legitimately change over time on Telegram's side — views,
    forwards, replies, pinned, edit_date, factcheck — are refreshed here.

    Stats counters (``views``, ``forwards``, ``replies``) are only emitted when
    Telegram returned a non-null value. Restricted/banned channels frequently
    return ``None`` for these, and writing that back would wipe the
    last-known-good counters; the caller layer also applies a monotonic guard
    to refuse outright downgrades.

    ``get_message`` / ``Message.from_telegram_object`` (force_update=True) is still
    the path used to write fresh content when adding messages for the first time.
    """
    replies_obj = getattr(telegram_message, "replies", None)
    fc = getattr(telegram_message, "factcheck", None)
    if fc is not None:
        text_obj = getattr(fc, "text", None)
        factcheck_data: dict | None = {
            "need_check": bool(getattr(fc, "need_check", False)),
            "country": getattr(fc, "country", None),
            "text": getattr(text_obj, "text", None) if text_obj else None,
        }
    else:
        factcheck_data = None
    update_kwargs: dict = {
        "pinned": bool(telegram_message.pinned),
        "edit_date": telegram_message.edit_date,
        "factcheck": factcheck_data,
        "_updated": now,
        "stats_refreshed_at": now,
    }
    if telegram_message.views is not None:
        update_kwargs["views"] = telegram_message.views
    if telegram_message.forwards is not None:
        update_kwargs["forwards"] = telegram_message.forwards
    replies_count = getattr(replies_obj, "replies", None)
    if replies_count is not None:
        update_kwargs["replies"] = replies_count
    if telegram_message.pinned:
        update_kwargs["has_been_pinned"] = True
    return update_kwargs


class ChannelCrawler:
    def __init__(
        self,
        api_client: TelegramAPIClient,
        media_handler: MediaHandler,
        reference_resolver: ReferenceResolver,
    ) -> None:
        self.api_client = api_client
        self.media_handler = media_handler
        self.reference_resolver = reference_resolver

    def set_more_channel_details(self, channel: Channel, telegram_channel: Any) -> None:
        if isinstance(telegram_channel, User):
            logger.warning("set_more_channel_details: %s resolved to a User entity; skipping", channel)
            Channel.objects.filter(pk=channel.pk).update(is_user_account=True, is_lost=False)
            return
        try:
            channel_full_info = self.api_client.client(GetFullChannelRequest(channel=telegram_channel))
        except TypeError as exc:
            # Telethon re-resolves the entity inside the request and may hand back an InputPeerUser.
            if "InputPeerUser" not in str(exc) or "InputChannel" not in str(exc):
                raise
            logger.warning(
                "set_more_channel_details: %s resolved to a user-type input peer; skipping (%s)", channel, exc
            )
            Channel.objects.filter(pk=channel.pk).update(is_user_account=True, is_lost=False)
            return
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
                    # Attribution is analyst-managed (time-bounded periods); a discovered linked
                    # chat starts unattributed.
                    Channel.from_telegram_object(linked_tg, force_update=False)
                except DatabaseError as exc:
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
            try:
                channel, tg_ch = self.get_basic_channel(seed)
                if channel is not None:
                    return channel, tg_ch, "ok"
                # get_basic_channel returned (None, None) without raising → invalid ID
                return None, None, "lost"
            except (errors.rpcerrorlist.ChannelPrivateError, ValueError) as exc:
                initial_private = isinstance(exc, errors.rpcerrorlist.ChannelPrivateError)

            # ── Fallback chain ────────────────────────────────────────────────
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
            # Reached only when nothing confirmed the channel: an initial
            # ChannelPrivateError that no fallback could re-confirm, or a
            # ValueError (Telethon had no cached access_hash) with no usable
            # access_hash/username fallback. Either way it is unresolvable →
            # "lost", not a user account. Genuine user accounts are caught by
            # the _UserAccountSeed handler below.
            return None, None, "lost"
        except _UserAccountSeed:
            # get_basic_channel — initial call or any fallback — saw a User entity.
            return None, None, "user_account"

    def get_basic_channel(self, seed: int | str) -> tuple[Channel, Any] | tuple[None, None]:
        self.api_client.wait()
        try:
            telegram_channel = self.api_client.client.get_entity(seed)
        except (errors.rpcerrorlist.ChannelInvalidError, errors.rpcerrorlist.UsernameInvalidError):
            logger.info("Not available seed: %s", seed)
            return None, None
        # ChannelPrivateError propagates so resolve_channel_or_classify() can distinguish it from "not found"
        if not telegram_channel:
            return None, None
        if isinstance(telegram_channel, User):
            # Don't build a Channel row from User fields — signal to the caller instead.
            raise _UserAccountSeed
        return Channel.from_telegram_object(telegram_channel, force_update=True), telegram_channel

    def refresh_channel_info(
        self,
        seed: int | str,
        status_callback: Callable[[str], None] | None = None,
    ) -> str:
        """Fetch and persist channel metadata (profile picture + full details). Returns the status string."""

        def update_status(message: str) -> None:
            if status_callback:
                status_callback(message)

        channel, telegram_channel, status = self.resolve_channel_or_classify(seed)
        if status == "private":
            Channel.objects.filter(Q(telegram_id=seed) | Q(username=seed)).update(is_private=True, is_lost=False)
            update_status(f"[telegram_id={seed}] | skipped (channel is private)")
            return status
        if status == "lost":
            Channel.objects.filter(Q(telegram_id=seed) | Q(username=seed)).update(is_lost=True, is_private=False)
            update_status(f"[telegram_id={seed}] | skipped (channel not found)")
            return status
        if status == "user_account":
            logger.info("Seed is a user account not resolvable by username: %s", seed)
            Channel.objects.filter(Q(telegram_id=seed) | Q(username=seed)).update(is_user_account=True, is_lost=False)
            update_status(f"[telegram_id={seed}] | skipped (user account)")
            return status

        channel_label = f"[id={channel.id}] {channel}"
        update_status(f"{channel_label} | fetching profile pictures")
        self.media_handler.download_profile_picture(telegram_channel)
        update_status(f"{channel_label} | fetching channel details")
        self.set_more_channel_details(channel, telegram_channel)
        update_status(f"{channel_label} | channel info updated")
        return "ok"

    def get_channel(
        self,
        seed: int | str,
        status_callback: Callable[[str], None] | None = None,
        fix_holes: bool = False,
        update_info: bool = True,
    ) -> int:
        """Crawl a channel and return the pre-crawl max telegram_id (0 if none existed).

        When ``update_info=False`` the channel metadata (profile picture, full details,
        and lost/private flags) is never written — only messages are fetched.
        """

        def update_status(message: str) -> None:
            if status_callback:
                status_callback(message)

        channel, telegram_channel, status = self.resolve_channel_or_classify(seed)
        if status == "private":
            if update_info:
                Channel.objects.filter(Q(telegram_id=seed) | Q(username=seed)).update(is_private=True, is_lost=False)
            else:
                logger.warning("Channel %s is private; skipping message fetch", seed)
            update_status(f"[telegram_id={seed}] | skipped (channel is private)")
            return 0
        if status == "lost":
            if update_info:
                Channel.objects.filter(Q(telegram_id=seed) | Q(username=seed)).update(is_lost=True, is_private=False)
            else:
                logger.warning("Channel %s not found; skipping message fetch", seed)
            update_status(f"[telegram_id={seed}] | skipped (channel not found)")
            return 0
        if status == "user_account":
            logger.info("Seed is a user account not resolvable by username: %s", seed)
            if update_info:
                Channel.objects.filter(Q(telegram_id=seed) | Q(username=seed)).update(
                    is_user_account=True, is_lost=False
                )
            update_status(f"[telegram_id={seed}] | skipped (user account)")
            return 0

        channel_label = f"[id={channel.id}] {channel}"
        if update_info:
            update_status(f"{channel_label} | fetching profile pictures")
            image_count = self.media_handler.download_profile_picture(telegram_channel)
            update_status(f"{channel_label} | fetching channel details")
            self.set_more_channel_details(channel, telegram_channel)
        else:
            image_count = 0

        id_agg = channel.message_set.aggregate(min_id=Min("telegram_id"), max_id=Max("telegram_id"))
        last_known_id = id_agg["max_id"] or 0
        message_count = 0
        update_status(f"{channel_label} | downloading recent messages")
        batch_count = 0
        for telegram_message in self.api_client.client.iter_messages(
            telegram_channel,
            min_id=last_known_id,
            wait_time=self.api_client.wait_time,
            reverse=True,
        ):
            stored, imgs = self.get_message(channel, telegram_message)
            image_count += imgs
            if stored:
                batch_count += 1
            update_status(f"{channel_label} | messages processed: {message_count + batch_count}")

        message_count += batch_count

        max_id = id_agg["min_id"] if not channel.are_messages_crawled else None

        batch_count = 0
        if max_id is not None:
            update_status(f"{channel_label} | downloading history")
            for telegram_message in self.api_client.client.iter_messages(
                telegram_channel, max_id=max_id, wait_time=self.api_client.wait_time
            ):
                stored, imgs = self.get_message(channel, telegram_message)
                image_count += imgs
                if stored:
                    batch_count += 1
                update_status(f"{channel_label} | messages processed: {message_count + batch_count}")

        message_count += batch_count

        if fix_holes:
            update_status(f"{channel_label} | checking for message holes")
            hole_message_count, hole_image_count = fix_message_holes(
                channel,
                telegram_channel,
                self.api_client,
                self.get_message,
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

    @staticmethod
    def _in_target_intervals(channel: Channel) -> list[tuple[Any, Any]]:
        """The channel's in-target (start, end) periods, cached on the instance for one crawl."""
        intervals = getattr(channel, "_in_target_intervals_cache", None)
        if intervals is None:
            intervals = list(channel.in_target_periods.values_list("start", "end"))
            channel._in_target_intervals_cache = intervals
        return intervals

    def _skip_out_of_target(self, channel: Channel, telegram_message: Any) -> bool:
        """True if the message must NOT be stored: dated outside the channel's in-target periods.

        ``to_inspect`` channels store everything; messages with no date are kept (can't classify).
        """
        if channel.to_inspect or not telegram_message.date:
            return False
        d = telegram_message.date.date()
        return not any((s is None or s <= d) and (e is None or e >= d) for s, e in self._in_target_intervals(channel))

    def _in_target_period_q(self, channel: Channel) -> Q | None:
        """Q over Message restricting to the channel's in-target periods (None = no restriction)."""
        if channel.to_inspect:
            return None
        intervals = self._in_target_intervals(channel)
        if not intervals:
            return None
        q = Q()
        for start, end in intervals:
            sub = Q()
            if start is not None:
                sub &= Q(date__date__gte=start)
            if end is not None:
                sub &= Q(date__date__lte=end)
            q |= sub
        return q

    def get_message(self, channel: Channel, telegram_message: Any) -> tuple[bool, int]:
        """Store *telegram_message* and return ``(stored, downloaded_images)``."""
        if isinstance(telegram_message, MessageService):
            return False, 0
        if self._skip_out_of_target(channel, telegram_message):
            return False, 0
        downloaded_images = 0
        message = Message.from_telegram_object(telegram_message, force_update=True, defaults={"channel": channel})

        if telegram_message.fwd_from:
            message.fwd_from_channel_post = getattr(telegram_message.fwd_from, "channel_post", None)
            message.fwd_from_from_name = getattr(telegram_message.fwd_from, "from_name", None) or ""
            message.fwd_from_date = getattr(telegram_message.fwd_from, "date", None)

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
            self.media_handler.download_message_audio(telegram_message)
            self.media_handler.download_message_sticker(telegram_message)
            self.media_handler.download_message_other_media(telegram_message)
            if hasattr(telegram_message.media, "photo"):
                message.media_type = "photo"
            elif hasattr(telegram_message.media, "document"):
                from crawler.media_handler import _is_audio, _is_sticker

                doc = telegram_message.media.document
                mime_type = getattr(doc, "mime_type", "") or ""
                if _is_sticker(doc):
                    message.media_type = "sticker"
                elif mime_type.startswith("video/"):
                    message.media_type = "video"
                elif _is_audio(doc):
                    message.media_type = "audio"
                else:
                    message.media_type = "document"
            elif hasattr(telegram_message.media, "poll"):
                message.media_type = "poll"
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
        _save_poll(message.pk, telegram_message)
        return True, downloaded_images

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
                # PeerChannel hints the entity type so Telethon's session cache does not
                # mis-resolve the raw int as a PeerUser when the channel is unknown to us.
                telegram_channel = self.api_client.client.get_entity(PeerChannel(channel_id))
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
            except (AttributeError, ValueError) as e:
                logger.warning("Could not resolve forwarded channel %s (%s); treating as private", channel_id, e)
                Message.objects.filter(pending_forward_telegram_id=channel_id).update(
                    forwarded_from_private=channel_id,
                    pending_forward_telegram_id=None,
                )

    def refresh_message_stats(
        self,
        channel: Channel,
        telegram_channel: Any,
        limit: int | None = None,
        min_date: datetime.date | None = None,
        max_date: datetime.date | None = None,
        max_telegram_id: int | None = None,
        status_callback: Callable[[str], None] | None = None,
    ) -> int:
        """Re-fetch messages and update views/forwards/pinned in place.

        ``limit`` restricts to the N most recent messages **within the date window**.
        ``min_date`` / ``max_date`` define the inclusive date window; iteration stops
        as soon as a message older than ``min_date`` is found.
        ``max_telegram_id``, when set, excludes messages freshly stored in the same run.
        ``_updated`` is explicitly stamped because QuerySet.update() bypasses auto_now.
        """

        def update_status(message: str) -> None:
            if status_callback:
                status_callback(message)

        Channel.objects.filter(pk=channel.pk).update(is_lost=False, is_private=False)
        now = timezone.now()
        from_cutoff: datetime.datetime | None = (
            datetime.datetime(min_date.year, min_date.month, min_date.day, tzinfo=datetime.timezone.utc)
            if min_date is not None
            else None
        )
        to_cutoff: datetime.datetime | None = (
            datetime.datetime.combine(
                max_date + datetime.timedelta(days=1), datetime.time.min, tzinfo=datetime.timezone.utc
            )
            if max_date is not None
            else None
        )
        # Compute iter_max_id: the most restrictive upper bound across pre-crawl max and max_date.
        # Telethon's max_id is exclusive (fetches id < max_id), so add 1 to each candidate.
        id_bounds: list[int] = []
        if max_telegram_id is not None and max_telegram_id > 0:
            id_bounds.append(max_telegram_id + 1)
        if to_cutoff is not None:
            to_max = Message.objects.filter(channel=channel, date__lt=to_cutoff).aggregate(Max("telegram_id"))[
                "telegram_id__max"
            ]
            if to_max is None:
                return 0  # no stored messages before to_cutoff
            id_bounds.append(to_max + 1)
        iter_max_id = min(id_bounds) if id_bounds else 0
        _total_qs = Message.objects.filter(channel=channel)
        if from_cutoff is not None:
            _total_qs = _total_qs.filter(date__gte=from_cutoff)
        if to_cutoff is not None:
            _total_qs = _total_qs.filter(date__lt=to_cutoff)
        if iter_max_id > 0:
            _total_qs = _total_qs.filter(telegram_id__lt=iter_max_id)
        period_q = self._in_target_period_q(channel)
        if period_q is not None:
            _total_qs = _total_qs.filter(period_q)
        db_ids_initial = set(_total_qs.values_list("telegram_id", flat=True))
        total_in_db = len(db_ids_initial)
        processed = 0
        updated = 0
        service_cleaned = 0
        newly_lost_inline = 0
        visited_ids: set[int] = set()
        limit_hit = False
        for telegram_message in self.api_client.client.iter_messages(
            telegram_channel,
            limit=None,
            wait_time=self.api_client.wait_time,
            max_id=iter_max_id,
        ):
            if from_cutoff is not None and telegram_message.date is not None and telegram_message.date < from_cutoff:
                break
            if to_cutoff is not None and telegram_message.date is not None and telegram_message.date >= to_cutoff:
                continue
            if self._skip_out_of_target(channel, telegram_message):
                continue
            if isinstance(telegram_message, MessageService):
                deleted, _ = Message.objects.filter(channel=channel, telegram_id=telegram_message.id).delete()
                if deleted:
                    service_cleaned += 1
                    total_in_db -= 1
                    visited_ids.add(telegram_message.id)
                continue
            processed += 1
            if limit is not None and processed > limit:
                limit_hit = True
                break
            update_kwargs = _build_msg_update_kwargs(telegram_message, now)
            msg_row = (
                Message.objects.filter(channel=channel, telegram_id=telegram_message.id)
                .values("pk", "replies_unavailable", "is_lost", "views", "forwards", "replies")
                .first()
            )
            if msg_row is not None:
                msg_pk = msg_row["pk"]
                # Tombstone detection: when a channel admin deletes a post Telegram
                # sometimes still returns a Message object for that id but stripped
                # of content. Treat that as a lost-state event — mark is_lost=True
                # and KEEP the previously-stored text and stats intact, rather than
                # overwriting them with the empty stub.
                is_tombstone = not (telegram_message.message or "") and not getattr(telegram_message, "media", None)
                if is_tombstone:
                    if not msg_row["is_lost"]:
                        Message.objects.filter(pk=msg_pk).update(is_lost=True)
                        newly_lost_inline += 1
                    visited_ids.add(telegram_message.id)
                    continue
                if msg_row["replies_unavailable"]:
                    update_kwargs.pop("replies", None)
                if msg_row["is_lost"]:
                    update_kwargs["is_lost"] = False
                # Monotonic stats guard: restricted-channel responses sometimes
                # return zero counters even when the post is still up. Refuse to
                # downgrade views/forwards/replies — keep the last-known-good
                # values when Telegram reports something lower.
                for stat in ("views", "forwards", "replies"):
                    new_val = update_kwargs.get(stat)
                    if new_val is None:
                        continue
                    old_val = msg_row.get(stat)
                    if old_val is not None and new_val < old_val:
                        update_kwargs.pop(stat)
                Message.objects.filter(pk=msg_pk).update(**update_kwargs)
                updated += 1
                visited_ids.add(telegram_message.id)
                _save_reactions(msg_pk, telegram_message)
                _save_poll(msg_pk, telegram_message)
            update_status(f"refreshing message stats … {updated}/{total_in_db}")
        newly_lost = 0
        if not limit_hit:
            missing_ids = db_ids_initial - visited_ids
            if missing_ids:
                newly_lost = Message.objects.filter(channel=channel, telegram_id__in=missing_ids, is_lost=False).update(
                    is_lost=True
                )
        notes: list[str] = []
        if service_cleaned:
            notes.append(f"{service_cleaned} service msg cleaned up")
        total_lost = newly_lost + newly_lost_inline
        if total_lost:
            notes.append(f"{total_lost} marked lost")
        suffix = f" ({', '.join(notes)})" if notes else ""
        update_status(f"refreshing message stats … {updated}/{total_in_db}{suffix}")
        return updated

    def retry_lost_messages(
        self,
        channel: Channel,
        telegram_channel: Any,
        status_callback: Callable[[str], None] | None = None,
    ) -> tuple[int, int]:
        """Re-fetch rows currently marked is_lost=True for *channel*.

        For each batch of up to 100 telegram_ids, calls client.get_messages.
        This is a pure existence probe: when Telegram returns a real message
        body, the local row's ``is_lost`` flag is cleared and nothing else
        is touched. The originally-captured text, views, forwards, reactions,
        media metadata, etc. stay exactly as they were — this prevents the
        Telegram-side restriction stub (e.g. "This channel can't be displayed
        because it violated Telegram's Terms of Service") from overwriting the
        real content we captured at first crawl.

        Returns (recovered, still_lost). MessageService rows are cleaned up
        like in refresh_message_stats.
        """

        def update_status(message: str) -> None:
            if status_callback:
                status_callback(message)

        lost_rows = list(Message.objects.filter(channel=channel, is_lost=True).values_list("pk", "telegram_id"))
        total = len(lost_rows)
        if total == 0:
            return 0, 0
        recovered = 0
        still_lost = 0
        now = timezone.now()
        BATCH = 100
        for i in range(0, total, BATCH):
            batch = lost_rows[i : i + BATCH]
            batch_pk_by_tid = {tid: pk for pk, tid in batch}
            batch_tids = [tid for _, tid in batch]
            self.api_client.wait()
            tg_messages = self.api_client.client.get_messages(telegram_channel, ids=batch_tids)
            for tg_msg in tg_messages:
                if tg_msg is None:
                    still_lost += 1
                    continue
                if isinstance(tg_msg, MessageService):
                    Message.objects.filter(channel=channel, telegram_id=tg_msg.id).delete()
                    recovered += 1
                    continue
                # Telegram occasionally returns a Message object stripped of all
                # content as a tombstone for a deleted post. Treat that as still
                # lost — the row stays is_lost=True and untouched.
                if not (tg_msg.message or "") and not getattr(tg_msg, "media", None):
                    still_lost += 1
                    continue
                msg_pk = batch_pk_by_tid.get(tg_msg.id)
                if msg_pk is None:
                    continue
                # Pure recovery probe: clear is_lost only — never overwrite
                # the stored text/stats/reactions. The bumped _updated marks
                # that the probe ran successfully.
                Message.objects.filter(pk=msg_pk).update(is_lost=False, _updated=now)
                recovered += 1
            update_status(f"retrying lost messages … {recovered + still_lost}/{total}")
        return recovered, still_lost

    def get_recommended_channels(self, channel: Channel) -> tuple[int, int]:
        """Fetch Telegram-recommended channels for *channel*. Returns (total_found, new_to_db)."""
        if not channel.access_hash:
            return 0, 0
        # GetChannelRecommendationsRequest only accepts broadcast channels; groups
        # and user accounts trigger an "Invalid channel object" RPC error.
        if channel.is_user_account or channel.megagroup or channel.gigagroup:
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
        except errors.RPCError as e:
            logger.warning("get_recommended_channels failed for channel_id=%s: %s", channel.telegram_id, e)
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
        min_telegram_id: int | None = None,
        max_telegram_id: int | None = None,
        status_callback: Callable[[str], None] | None = None,
    ) -> int:
        """Fetch and upsert reply messages for posts in *channel* with replies > 0.

        ``min_telegram_id`` / ``max_telegram_id`` restrict which parent messages are processed.
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

        parent_qs = Message.objects.filter(channel=channel, replies__gt=0, replies_unavailable=False)
        if min_telegram_id is not None:
            parent_qs = parent_qs.filter(telegram_id__gte=min_telegram_id)
        if max_telegram_id is not None:
            parent_qs = parent_qs.filter(telegram_id__lte=max_telegram_id)
        parent_messages = list(parent_qs.values_list("pk", "telegram_id"))
        if not parent_messages:
            return 0

        total_upserted = 0
        total_parents = len(parent_messages)
        for done, (msg_pk, msg_telegram_id) in enumerate(parent_messages, 1):
            if status_callback:
                status_callback(
                    f"[id={channel.id}] {channel} | replies for post #{msg_telegram_id} ({done}/{total_parents})"
                )
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
                Message.objects.filter(pk=msg_pk).update(replies_fetched=True)
            except errors.FloodWaitError:
                raise
            except errors.rpcerrorlist.ChannelPrivateError:
                logger.warning("ChannelPrivateError fetching replies for post %s in %s", msg_telegram_id, channel)
            except (errors.rpcerrorlist.MessageIdInvalidError, errors.rpcerrorlist.MsgIdInvalidError) as exc:
                logger.debug(
                    "MessageIdInvalid for post %s in %s [%s]; marking unavailable",
                    msg_telegram_id,
                    channel,
                    type(exc).__name__,
                )
                Message.objects.filter(pk=msg_pk).update(replies_unavailable=True, replies_fetched=True)
            except errors.RPCError as exc:
                logger.warning("Error fetching replies for post %s in %s: %s", msg_telegram_id, channel, exc)

        return total_upserted

    def get_missing_references(self, status_callback=None, force_retry: bool = False, channel_qs=None) -> None:
        self.reference_resolver.get_missing_references(
            status_callback=status_callback, force_retry=force_retry, channel_qs=channel_qs
        )
