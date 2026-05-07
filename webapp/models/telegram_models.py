import datetime
import re
from typing import TYPE_CHECKING, Any, ClassVar

if TYPE_CHECKING:
    from webapp.models.media_models import MessagePicture, MessageVideo, ProfilePicture

from django.conf import settings
from django.db import models
from django.db.models import F, Max, Min, Q
from django.urls import reverse

from webapp.managers import ChannelManager
from webapp.models import Organization
from webapp.models.base import TelegramBaseModel


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
    is_user_account = models.BooleanField(default=False)
    are_messages_crawled = models.BooleanField(default=False)
    last_hole_check_max_telegram_id = models.PositiveBigIntegerField(null=True)
    organization = models.ForeignKey(Organization, on_delete=models.SET_NULL, blank=True, null=True)
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
    uninteresting_after = models.DateField(null=True, blank=True)
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

    def _get_activity_bounds(
        self,
    ) -> tuple["datetime.datetime | None", "datetime.datetime | None"]:
        qs = self.message_set.exclude(date__isnull=True)
        if self.uninteresting_after:
            qs = qs.filter(date__date__lte=self.uninteresting_after)
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
        refresh_cited_degree() for non-interesting channels.
        """
        cited_by = (
            Message.objects.filter(channel__in=Channel.objects.interesting())
            .filter(Q(forwarded_from=self) | Q(references=self))
            .filter(Q(channel__uninteresting_after__isnull=True) | Q(date__date__lte=F("channel__uninteresting_after")))
            .exclude(channel=self)
            .distinct()
            .count()
        )
        cites_qs = (
            Message.objects.filter(channel=self)
            .filter(
                Q(forwarded_from__in=Channel.objects.interesting()) | Q(references__in=Channel.objects.interesting())
            )
            .exclude(forwarded_from=self)
            .distinct()
        )
        if self.uninteresting_after:
            cites_qs = cites_qs.filter(date__date__lte=self.uninteresting_after)
        cites = cites_qs.count()
        if settings.REVERSED_EDGES:
            self._set_degrees(cited_by, cites)
        else:
            self._set_degrees(cites, cited_by)

    def refresh_cited_degree(self) -> None:
        """Recompute and persist the citation count for a non-interesting channel.

        Counts how many messages from interesting channels cite this channel (via
        forwards or t.me/username references) and stores the total in the field that
        matches the graph edge direction:
          - in_degree  when REVERSED_EDGES=True  (citations arrive as incoming edges)
          - out_degree when REVERSED_EDGES=False (citations leave as outgoing edges)
        The other field is set to 0.
        """
        citations = (
            Message.objects.filter(channel__in=Channel.objects.interesting())
            .filter(Q(forwarded_from=self) | Q(references=self))
            .filter(Q(channel__uninteresting_after__isnull=True) | Q(date__date__lte=F("channel__uninteresting_after")))
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
    channel = models.ForeignKey(Channel, on_delete=models.CASCADE, related_name="message_set")
    date = models.DateTimeField(null=True)
    out = models.BooleanField(default=False)
    mentioned = models.BooleanField(default=False)
    post = models.BooleanField(default=False)
    from_scheduled = models.BooleanField(default=False, null=True)
    message = models.TextField(blank=True)
    forwarded_from = models.ForeignKey(
        Channel, on_delete=models.SET_NULL, null=True, related_name="forwarded_message_set"
    )
    forwarded_from_private = models.PositiveBigIntegerField(null=True)
    pending_forward_telegram_id = models.PositiveBigIntegerField(null=True)

    references = models.ManyToManyField(Channel, related_name="reference_message_set")
    missing_references = models.TextField(blank=True)
    grouped_id = models.BigIntegerField(null=True)
    views = models.PositiveBigIntegerField(null=True)
    forwards = models.PositiveBigIntegerField(null=True)
    edit_date = models.DateTimeField(null=True)
    post_author = models.CharField(max_length=255, blank=True)
    pinned = models.BooleanField(null=True, default=False)
    has_been_pinned = models.BooleanField(default=False)
    webpage_url = models.URLField(max_length=255, default="", blank=True)
    webpage_type = models.CharField(max_length=255, default="", blank=True)
    media_type = models.CharField(
        max_length=32, default="", blank=True
    )  # "photo", "video", "audio", "document", "poll", or ""
    replies = models.PositiveBigIntegerField(null=True)
    replies_unavailable = models.BooleanField(default=False)
    silent = models.BooleanField(default=False)
    reply_to_msg_id = models.PositiveBigIntegerField(null=True)
    fwd_from_channel_post = models.PositiveBigIntegerField(null=True)
    fwd_from_from_name = models.CharField(max_length=255, blank=True)
    factcheck = models.JSONField(null=True, blank=True)

    def __str__(self) -> str:
        return f"{self.channel.title} [{self.date or self.telegram_id}]"

    def save(self, *args: Any, **kwargs: Any) -> None:
        for field in ("message", "post_author", "webpage_url", "webpage_type", "media_type", "fwd_from_from_name"):
            setattr(self, field, getattr(self, field) or "")
        if self.pinned:
            self.has_been_pinned = True
        super().save(*args, **kwargs)

    @classmethod
    def _args_for_from_telegram_object(cls, telegram_object: Any) -> dict[str, Any]:
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
