import datetime
import re
from collections.abc import Iterable
from typing import TYPE_CHECKING, Any, ClassVar

if TYPE_CHECKING:
    from webapp.models.media_models import (
        MessageAudio,
        MessageOtherMedia,
        MessagePicture,
        MessageSticker,
        MessageVideo,
        ProfilePicture,
    )
    from webapp.models.organization_models import ChannelAttribution, Organization

from django.conf import settings
from django.db import models
from django.db.models import Max, Min, Q
from django.urls import reverse

from webapp.managers import ChannelManager, MessageManager
from webapp.models.base import TelegramBaseModel
from webapp.utils.emoji import emoji_present


class Channel(TelegramBaseModel):
    TELEGRAM_OBJECT_PROPERTIES: ClassVar[tuple[str, ...]] = (
        "title",
        "date",
        "broadcast",
        "verified",
        "megagroup",
        "restricted",
        "signatures",
        "min",
        "scam",
        "has_link",
        "has_geo",
        "slowmode_enabled",
        "fake",
        "gigagroup",
        "access_hash",
        "username",
        "noforwards",
        "forum",
        "join_to_send",
        "join_request",
        "level",
    )

    objects = ChannelManager()

    title = models.CharField(max_length=255, blank=True)
    about = models.TextField(blank=True)
    telegram_location = models.TextField(blank=True)
    username = models.CharField(max_length=255, blank=True)
    date = models.DateTimeField(null=True)
    participants_count = models.PositiveBigIntegerField(null=True)
    is_active = models.BooleanField(default=False)
    is_lost = models.BooleanField(default=False)
    is_private = models.BooleanField(default=False)
    to_inspect = models.BooleanField(default=False)
    is_user_account = models.BooleanField(default=False)
    are_messages_crawled = models.BooleanField(default=False)
    last_hole_check_max_telegram_id = models.PositiveBigIntegerField(null=True)
    broadcast = models.BooleanField(default=True)
    verified = models.BooleanField(default=False)
    megagroup = models.BooleanField(default=False)
    gigagroup = models.BooleanField(default=False)
    restricted = models.BooleanField(default=False)
    signatures = models.BooleanField(default=False)
    min = models.BooleanField(default=False)
    scam = models.BooleanField(default=False)
    has_link = models.BooleanField(default=False)
    has_geo = models.BooleanField(default=False)
    slowmode_enabled = models.BooleanField(default=False)
    fake = models.BooleanField(default=False)
    access_hash = models.BigIntegerField(null=True)
    in_degree = models.PositiveIntegerField(null=True)
    out_degree = models.PositiveIntegerField(null=True)
    restriction_reason = models.JSONField(null=True, blank=True)
    message_ttl = models.PositiveIntegerField(null=True, blank=True)
    noforwards = models.BooleanField(default=False)
    forum = models.BooleanField(default=False)
    join_to_send = models.BooleanField(default=False)
    join_request = models.BooleanField(default=False)
    level = models.PositiveIntegerField(null=True, blank=True)
    extra_usernames = models.JSONField(null=True, blank=True)
    linked_chat_id = models.BigIntegerField(null=True, blank=True)
    available_min_id = models.PositiveBigIntegerField(null=True, blank=True)
    slowmode_seconds = models.PositiveIntegerField(null=True, blank=True)
    admins_count = models.PositiveIntegerField(null=True, blank=True)
    online_count = models.PositiveIntegerField(null=True, blank=True)
    requests_pending = models.PositiveIntegerField(null=True, blank=True)
    theme_emoticon = models.CharField(max_length=20, blank=True)
    boosts_applied = models.PositiveIntegerField(null=True, blank=True)
    boosts_unrestrict = models.PositiveIntegerField(null=True, blank=True)
    kicked_count = models.PositiveIntegerField(null=True, blank=True)
    banned_count = models.PositiveIntegerField(null=True, blank=True)
    antispam = models.BooleanField(default=False)
    has_scheduled = models.BooleanField(default=False)
    pinned_msg_id = models.PositiveBigIntegerField(null=True, blank=True)
    migrated_from_chat_id = models.BigIntegerField(null=True, blank=True)

    def __str__(self) -> str:
        return self.title or str(self.telegram_id)

    def get_absolute_url(self) -> str:
        return reverse("channel-detail", kwargs={"pk": self.pk})

    @property
    def telegram_url(self) -> str:
        return f"https://t.me/{self.username or self.telegram_id}"

    @property
    def channel_type(self) -> str:
        if self.is_user_account:
            return "user"
        if self.gigagroup:
            return "gigagroup"
        if self.megagroup:
            return "supergroup"
        if self.broadcast:
            return "channel"
        return "unknown"

    @property
    def profile_picture(self) -> "ProfilePicture | None":
        if hasattr(self, "_prefetched_profile_pics"):
            pics = self._prefetched_profile_pics
            return pics[0] if pics else None
        return self.profilepicture_set.order_by("-date").first()

    @property
    def in_target_periods(self) -> "models.QuerySet[ChannelAttribution]":
        """Attribution periods whose organization is currently in target."""
        return self.attributions.filter(organization__is_in_target=True)

    @property
    def current_attribution(self) -> "ChannelAttribution | None":
        """The attribution that best represents the channel *now*.

        The period active today wins (null bounds count as open); otherwise the
        most recent past period (largest ``end``, tie → latest ``start``);
        otherwise the earliest known period. ``None`` when the channel has no
        attribution at all.
        """
        today = datetime.date.today()
        attrs = list(self.attributions.all())  # prefetch-friendly; callers iterating many channels prefetch
        if not attrs:
            return None
        active = [a for a in attrs if (a.start is None or a.start <= today) and (a.end is None or a.end >= today)]
        if active:
            return max(active, key=lambda a: (a.start or datetime.date.min))
        past = [a for a in attrs if a.end is not None and a.end < today]
        if past:
            return max(past, key=lambda a: (a.end, a.start or datetime.date.min))
        return min(attrs, key=lambda a: (a.start or datetime.date.min))

    @property
    def current_organization(self) -> "Organization | None":
        attribution = self.current_attribution
        return attribution.organization if attribution else None

    def _get_activity_bounds(
        self,
    ) -> tuple["datetime.datetime | None", "datetime.datetime | None"]:
        qs = self.message_set.exclude(date__isnull=True)
        # Restrict to in-target periods when the channel has any; an unattributed channel
        # (or to_inspect-only) shows its full message span. One periods query + one aggregate.
        intervals = list(self.in_target_periods.values_list("start", "end"))
        if intervals:
            period_q = Q()
            for start, end in intervals:
                sub = Q()
                if start is not None:
                    sub &= Q(date__date__gte=start)
                if end is not None:
                    sub &= Q(date__date__lte=end)
                period_q |= sub
            qs = qs.filter(period_q)
        agg = qs.aggregate(min_date=Min("date"), max_date=Max("date"))
        first_date = agg["min_date"]
        last_date = agg["max_date"]
        start_candidates = [d for d in (self.date, first_date) if d is not None]
        end_candidates = [d for d in (self.date, last_date) if d is not None]
        return (
            min(start_candidates) if start_candidates else None,
            max(end_candidates) if end_candidates else None,
        )

    @property
    def activity_period(self) -> str:
        start, end = self._get_activity_bounds()
        if start is None or end is None:
            return "Unknown"
        date_template = "%b %Y"
        return (
            f"{start.strftime(date_template)} - {end.strftime(date_template)}"
            if end < datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=30)
            else f"{start.strftime(date_template)} - "
        )

    def save(self, *args: Any, **kwargs: Any) -> None:
        self.username = self.username or ""
        super().save(*args, **kwargs)

    def _set_degrees(self, in_degree: int, out_degree: int) -> None:
        """Persist in_degree/out_degree to the DB and update the in-memory instance."""
        Channel.objects.filter(pk=self.pk).update(in_degree=in_degree, out_degree=out_degree)
        self.in_degree = in_degree
        self.out_degree = out_degree

    def refresh_degrees(self) -> None:
        """Recompute and persist in_degree and out_degree from current message data.

        Counts both forwarded-from citations and t.me/username reference citations,
        matching the edge construction in graph_builder. Respects REVERSED_EDGES:
        when True, citations are incoming edges (stored in in_degree); when False,
        citations are outgoing edges (stored in out_degree), consistent with
        refresh_cited_degree() for out-of-target channels.
        """
        from network.utils import channel_cutoff_q

        cited_by = (
            Message.objects.alive()
            .filter(channel__in=Channel.objects.in_target())
            .filter(Q(forwarded_from=self) | Q(references=self))
            .filter(channel_cutoff_q())
            .exclude(channel=self)
            .distinct()
            .count()
        )
        cites = (
            Message.objects.alive()
            .filter(channel=self)
            .filter(Q(forwarded_from__in=Channel.objects.in_target()) | Q(references__in=Channel.objects.in_target()))
            .filter(channel_cutoff_q())
            .exclude(forwarded_from=self)
            .distinct()
            .count()
        )
        if settings.REVERSED_EDGES:
            self._set_degrees(cited_by, cites)
        else:
            self._set_degrees(cites, cited_by)

    def refresh_cited_degree(self) -> None:
        """Recompute and persist the citation count for a out-of-target channel.

        Counts how many messages from in-target channels cite this channel (via
        forwards or t.me/username references) and stores the total in the field that
        matches the graph edge direction:
          - in_degree  when REVERSED_EDGES=True  (citations arrive as incoming edges)
          - out_degree when REVERSED_EDGES=False (citations leave as outgoing edges)
        The other field is set to 0.
        """
        from network.utils import channel_cutoff_q

        citations = (
            Message.objects.alive()
            .filter(channel__in=Channel.objects.in_target())
            .filter(Q(forwarded_from=self) | Q(references=self))
            .filter(channel_cutoff_q())
            .exclude(channel=self)
            .distinct()
            .count()
        )
        if settings.REVERSED_EDGES:
            self._set_degrees(citations, 0)
        else:
            self._set_degrees(0, citations)


class Message(TelegramBaseModel):
    TELEGRAM_OBJECT_PROPERTIES: ClassVar[tuple[str, ...]] = (
        "date",
        "edit_date",
        "post_author",
        "out",
        "mentioned",
        "post",
        "from_scheduled",
        "message",
        "grouped_id",
        "views",
        "forwards",
        "pinned",
        "silent",
    )
    objects = MessageManager()

    channel = models.ForeignKey(Channel, on_delete=models.CASCADE, related_name="message_set")
    date = models.DateTimeField(null=True)
    is_lost = models.BooleanField(default=False, db_index=True)
    out = models.BooleanField(default=False)
    mentioned = models.BooleanField(default=False)
    post = models.BooleanField(default=False)
    from_scheduled = models.BooleanField(default=False, null=True)
    message = models.TextField(blank=True)
    forwarded_from = models.ForeignKey(
        Channel, on_delete=models.SET_NULL, null=True, related_name="forwarded_message_set"
    )
    # Crawler-internal: written by ``ChannelCrawler._resolve_pending_forwards`` when a
    # forwarded post originated from a private channel we couldn't resolve. Preserved
    # so the originator's telegram_id isn't lost; not yet rendered anywhere on the
    # public site, but the data sticks around for a future "forwarded from private"
    # affordance.
    forwarded_from_private = models.PositiveBigIntegerField(null=True)
    # Crawler-internal: the telegram_id of a forwarded channel we couldn't resolve
    # in-line during get_message. Cleared once the deferred lookup succeeds (in
    # ``_resolve_pending_forwards``); never read by the public-facing views.
    pending_forward_telegram_id = models.PositiveBigIntegerField(null=True)

    references = models.ManyToManyField(Channel, related_name="reference_message_set")
    missing_references = models.TextField(blank=True)
    grouped_id = models.BigIntegerField(null=True, db_index=True)
    views = models.PositiveBigIntegerField(null=True)
    total_reactions = models.PositiveBigIntegerField(default=0)
    forwards = models.PositiveBigIntegerField(null=True)
    edit_date = models.DateTimeField(null=True)
    post_author = models.CharField(max_length=255, blank=True)
    pinned = models.BooleanField(null=True, default=False)
    has_been_pinned = models.BooleanField(default=False)
    webpage_url = models.URLField(max_length=255, default="", blank=True)
    webpage_type = models.CharField(max_length=255, default="", blank=True)
    media_type = models.CharField(
        max_length=32, default="", blank=True
    )  # "photo", "video", "audio", "sticker", "document", "poll", "none", "gone" (no longer on Telegram), or ""
    replies = models.PositiveBigIntegerField(null=True)
    replies_fetched = models.BooleanField(default=False)
    replies_unavailable = models.BooleanField(default=False)
    silent = models.BooleanField(default=False)
    reply_to_msg_id = models.PositiveBigIntegerField(null=True)
    fwd_from_channel_post = models.PositiveBigIntegerField(null=True)
    fwd_from_from_name = models.CharField(max_length=255, blank=True)
    fwd_from_date = models.DateTimeField(null=True)
    factcheck = models.JSONField(null=True, blank=True)
    stats_refreshed_at = models.DateTimeField(null=True)

    # Per-channel z-scores of the three engagement facets. NULL when the
    # facet is itself NULL on the message, or when the channel has fewer than
    # webapp.scoring.MIN_SAMPLE rated messages (cold-start). Salganik–Dodds–Watts
    # 2006 normalisation against rich-get-richer bias.
    z_views = models.FloatField(null=True)
    z_forwards = models.FloatField(null=True)
    z_reactions = models.FloatField(null=True)
    # Weighted composite of the available z-scores (Suh et al. 2010 / Cha et al.
    # 2010 weights). NULL when all three facet z-scores are NULL.
    interest_score = models.FloatField(null=True, db_index=True)
    interest_scored_at = models.DateTimeField(null=True)

    class Meta:
        indexes = [
            # Speeds up the in_target() + Message.alive() pattern used by every
            # home / search / channel-detail page aggregate.
            models.Index(fields=["channel", "is_lost"], name="webapp_msg_chan_lost_idx"),
            # Speeds up Min/Max(date) aggregates and per-channel date-range
            # filters (channel-detail timeline, structural_analysis).
            models.Index(fields=["channel", "date"], name="webapp_msg_chan_date_idx"),
            # Per-channel sort by views / reactions on the messages browser.
            models.Index(fields=["channel", "views"], name="webapp_msg_chan_views_idx"),
            models.Index(fields=["channel", "total_reactions"], name="webapp_msg_chan_react_idx"),
            # Per-channel sort by interest_score for the "Top messages" panel.
            models.Index(fields=["channel", "interest_score"], name="webapp_msg_chan_interest_idx"),
        ]

    def __str__(self) -> str:
        return f"{self.channel.title} [{self.date or self.telegram_id}]"

    def save(self, *args: Any, **kwargs: Any) -> None:
        for field in ("message", "post_author", "webpage_url", "webpage_type", "media_type", "fwd_from_from_name"):
            setattr(self, field, getattr(self, field) or "")
        if self.pinned:
            self.has_been_pinned = True
        super().save(*args, **kwargs)

    @classmethod
    def _args_for_from_telegram_object(
        cls, telegram_object: Any, defaults: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        return {"telegram_id": telegram_object.id, "channel__telegram_id": telegram_object.peer_id.channel_id}

    def get_telegram_references(self) -> list[str]:
        return [url[5:] for url in re.findall(r"t\.me/(?:[-\w.]|(?:%[\da-fA-F]{2}))+", str(self.message))]

    @property
    def message_picture(self) -> "MessagePicture | None":
        return self.messagepicture_set.order_by("date").last()

    @property
    def message_video(self) -> "MessageVideo | None":
        return self.messagevideo_set.order_by("date").last()

    @property
    def message_audio(self) -> "MessageAudio | None":
        return self.messageaudio_set.order_by("date").last()

    @property
    def message_sticker(self) -> "MessageSticker | None":
        return self.messagesticker_set.order_by("date").last()

    @property
    def message_other_media(self) -> "MessageOtherMedia | None":
        return self.messageothermedia_set.order_by("date").last()

    @property
    def is_album(self) -> bool:
        return self.grouped_id is not None

    def _album_media(self, cache_key: str, related_set_name: str, model: type) -> list:
        """Return either prefetched single-message media or all album-sibling media.

        For non-album messages this returns the prefetched related set, so the
        existing prefetch_related calls keep their N+1 protection. For album
        heads it returns the cache populated by :meth:`attach_album_data`
        (when the view called it on the paginated page), or falls back to a
        per-message query — ordered by sibling telegram_id so the gallery
        matches Telegram's order.
        """
        if not self.is_album:
            return list(getattr(self, related_set_name).all())
        cache = getattr(self, "_album_cache", None)
        if cache is not None:
            return cache.get(cache_key, [])
        return list(
            model.objects.filter(
                message__channel_id=self.channel_id,
                message__grouped_id=self.grouped_id,
            ).order_by("message__telegram_id")
        )

    @property
    def album_pictures(self) -> list:
        from webapp.models.media_models import MessagePicture

        return self._album_media("pictures", "messagepicture_set", MessagePicture)

    @property
    def album_videos(self) -> list:
        from webapp.models.media_models import MessageVideo

        return self._album_media("videos", "messagevideo_set", MessageVideo)

    @property
    def album_audios(self) -> list:
        from webapp.models.media_models import MessageAudio

        return self._album_media("audios", "messageaudio_set", MessageAudio)

    @property
    def album_stickers(self) -> list:
        from webapp.models.media_models import MessageSticker

        return self._album_media("stickers", "messagesticker_set", MessageSticker)

    @property
    def album_other_media(self) -> list:
        from webapp.models.media_models import MessageOtherMedia

        return self._album_media("other_media", "messageothermedia_set", MessageOtherMedia)

    @property
    def album_size(self) -> int:
        """Number of messages in this album (1 for non-album messages)."""
        if not self.is_album:
            return 1
        cached = getattr(self, "_album_size_cache", None)
        if cached is not None:
            return cached
        return Message.objects.filter(channel_id=self.channel_id, grouped_id=self.grouped_id).count()

    _ALBUM_CACHE_KEYS: ClassVar[tuple[str, ...]] = ("pictures", "videos", "audios", "stickers", "other_media")

    # Map each `Message.media_type` string a sibling carries to (a) the album-
    # cache key used by `_album_media` / `album_pictures` / `album_videos` /
    # …, and (b) the name of the file field on the corresponding media model
    # whose truthiness tells us the file actually downloaded.
    _MEDIA_TYPE_INFO: ClassVar[dict[str, tuple[str, str]]] = {
        "photo": ("pictures", "picture"),
        "video": ("videos", "video"),
        "audio": ("audios", "audio"),
        "sticker": ("stickers", "sticker"),
        "document": ("other_media", "media_file"),
    }

    def _expected_media_count(self, media_type: str) -> int:
        """How many sibling messages in this album carry `media_type` on their Message row.

        For a non-album message, this is `1` when the message itself is of that
        type and `0` otherwise. For an album head, it reflects the union over
        every sibling sharing `(channel_id, grouped_id)` — cached by
        `attach_album_data` when present, otherwise a single COUNT() per call.
        """
        if not self.is_album:
            return 1 if self.media_type == media_type else 0
        cache = getattr(self, "_album_sibling_type_counts", None)
        if cache is not None:
            return cache.get(media_type, 0)
        return Message.objects.filter(
            channel_id=self.channel_id, grouped_id=self.grouped_id, media_type=media_type
        ).count()

    def _missing_media_placeholders(self, media_type: str) -> list:
        """Return a list of length N (= sibling-count − downloaded-row-count) for templates.

        The template loops it to render N placeholder cards. Only sibling rows
        whose underlying file field is truthy count as "downloaded" — a media
        row whose file went missing from disk is still treated as a missing
        placeholder, not as a silent blank.
        """
        info = self._MEDIA_TYPE_INFO.get(media_type)
        if not info:
            return []
        cache_key, file_attr = info
        # Use the existing album_* properties so we benefit from the
        # attach_album_data cache when the view called it.
        media_rows = getattr(self, f"album_{cache_key}")
        actual = sum(1 for row in media_rows if getattr(row, file_attr, None))
        expected = self._expected_media_count(media_type)
        return [None] * max(0, expected - actual)

    @property
    def album_missing_pictures(self) -> list:
        return self._missing_media_placeholders("photo")

    @property
    def album_missing_videos(self) -> list:
        return self._missing_media_placeholders("video")

    @property
    def album_missing_audios(self) -> list:
        return self._missing_media_placeholders("audio")

    @property
    def album_missing_stickers(self) -> list:
        return self._missing_media_placeholders("sticker")

    @property
    def album_missing_other_media(self) -> list:
        return self._missing_media_placeholders("document")

    @classmethod
    def attach_album_data(cls, messages: "Iterable[Message]") -> None:
        """Bulk-load album sibling media and sizes for a page of messages.

        Without this, every album message on the page fires one query per
        media model in :meth:`_album_media` (and another for ``album_size``)
        when the template iterates the gallery. This method collapses those
        N × 6 round-trips into 6 queries total:

        * 1 query to find all album-sibling Message rows for the page and
          count them per ``(channel_id, grouped_id)`` pair.
        * 5 queries, one per media model, fetching every sibling media row
          and grouping by the same key.

        The results are stored on each album head as ``_album_cache`` (a
        dict keyed by media type) and ``_album_size_cache`` (an int). The
        property getters read these caches first; if absent (e.g. the view
        didn't call this) they fall back to the original per-message query
        so existing call sites stay correct.
        """
        from collections import defaultdict
        from functools import reduce
        from operator import or_

        from webapp.models.media_models import (
            MessageAudio,
            MessageOtherMedia,
            MessagePicture,
            MessageSticker,
            MessageVideo,
        )

        materialised = list(messages)
        album_keys = {(m.channel_id, m.grouped_id) for m in materialised if m.is_album}
        if not album_keys:
            return

        q = reduce(or_, (Q(channel_id=c, grouped_id=g) for c, g in album_keys))
        sibling_rows = list(cls.objects.filter(q).values("id", "channel_id", "grouped_id", "media_type"))

        sibling_ids: list[int] = []
        sizes: dict[tuple[int, int], int] = defaultdict(int)
        # Per-album-key counts of sibling messages whose `media_type` is the
        # given value. Powers the `album_missing_*` placeholder properties so
        # a video sibling whose file wasn't downloaded still shows up as a
        # placeholder in the gallery.
        sibling_type_counts: dict[tuple[int, int], dict[str, int]] = defaultdict(lambda: defaultdict(int))
        for row in sibling_rows:
            sibling_ids.append(row["id"])
            key = (row["channel_id"], row["grouped_id"])
            sizes[key] += 1
            if row["media_type"]:
                sibling_type_counts[key][row["media_type"]] += 1

        media_lookups: dict[tuple[int, int], dict[str, list]] = {}
        media_configs = (
            ("pictures", MessagePicture),
            ("videos", MessageVideo),
            ("audios", MessageAudio),
            ("stickers", MessageSticker),
            ("other_media", MessageOtherMedia),
        )
        for cache_key, media_model in media_configs:
            qs = media_model.objects.filter(message_id__in=sibling_ids).select_related("message")
            for media in qs.order_by("message__telegram_id"):
                key = (media.message.channel_id, media.message.grouped_id)
                bucket = media_lookups.get(key)
                if bucket is None:
                    bucket = {k: [] for k in cls._ALBUM_CACHE_KEYS}
                    media_lookups[key] = bucket
                bucket[cache_key].append(media)

        for msg in materialised:
            if not msg.is_album:
                continue
            key = (msg.channel_id, msg.grouped_id)
            msg._album_cache = media_lookups.get(key, {k: [] for k in cls._ALBUM_CACHE_KEYS})
            msg._album_size_cache = sizes.get(key, 1)
            msg._album_sibling_type_counts = dict(sibling_type_counts.get(key, {}))

    @property
    def telegram_url(self) -> str:
        return f"{self.channel.telegram_url}/{self.telegram_id}"


class MessageReaction(models.Model):
    """Aggregated reaction count for a single emoji on a single message."""

    message = models.ForeignKey(Message, on_delete=models.CASCADE, related_name="reactions")
    emoji = models.CharField(max_length=64)
    count = models.PositiveIntegerField(default=0)

    class Meta:
        unique_together = [("message", "emoji")]
        ordering = ["-count"]

    def __str__(self) -> str:
        return f"{self.emoji} ×{self.count} on message {self.message_id}"

    @property
    def display_emoji(self) -> str:
        return emoji_present(self.emoji)


class MessageReply(models.Model):
    """An individual reply to a channel post, fetched from the linked discussion group."""

    parent_message = models.ForeignKey(Message, on_delete=models.CASCADE, related_name="reply_set")
    telegram_id = models.BigIntegerField()
    date = models.DateTimeField(null=True)
    text = models.TextField(blank=True)
    sender_name = models.CharField(max_length=255, blank=True)
    sender_id = models.BigIntegerField(null=True)
    views = models.PositiveBigIntegerField(null=True)

    class Meta:
        unique_together = [("parent_message", "telegram_id")]
        ordering = ["date"]

    def __str__(self) -> str:
        return f"Reply {self.telegram_id} to message {self.parent_message_id}"


class Poll(models.Model):
    message = models.OneToOneField(Message, on_delete=models.CASCADE, related_name="poll")
    poll_id = models.BigIntegerField()
    question = models.TextField()
    closed = models.BooleanField(default=False)
    public_voters = models.BooleanField(default=False)
    multiple_choice = models.BooleanField(default=False)
    quiz = models.BooleanField(default=False)
    close_date = models.DateTimeField(null=True, blank=True)
    total_voters = models.PositiveIntegerField(null=True, blank=True)
    solution = models.TextField(blank=True)

    def __str__(self) -> str:
        return f"Poll {self.poll_id} on message {self.message_id}"


class PollAnswer(models.Model):
    poll = models.ForeignKey(Poll, on_delete=models.CASCADE, related_name="answers")
    option = models.BinaryField(max_length=8)
    text = models.TextField()
    voters = models.PositiveIntegerField(default=0)
    correct = models.BooleanField(null=True)

    class Meta:
        unique_together = [("poll", "option")]
        ordering = ["id"]

    def __str__(self) -> str:
        return f"Option {self.option!r} on poll {self.poll_id} ({self.voters} voters)"
