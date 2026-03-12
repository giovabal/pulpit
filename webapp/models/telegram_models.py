import datetime
import os
import re
from typing import Any, ClassVar, Self

from django.conf import settings
from django.core.files import File
from django.db import models
from django.db.models import Max, Min
from django.urls import reverse

from webapp.managers import ChannelManager
from webapp.models import Organization
from webapp.models.base import TelegramBaseModel, TelegramBasePictureModel, _telegram_picture_upload_to_function
from webapp.utils.colors import hex_to_rgb


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
        return self.profilepicture_set.order_by("date").last()

    def _get_activity_bounds(
        self,
    ) -> tuple["datetime.datetime | None", "datetime.datetime | None"]:
        agg = self.message_set.exclude(date__isnull=True).aggregate(min_date=Min("date"), max_date=Max("date"))
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

    def network_data(self, default: dict[str, Any] | None = None) -> dict[str, Any]:
        default = default or {}
        data: dict[str, Any] = {
            "pk": str(self.pk),
            "id": self.telegram_id,
            "label": self.title,
            "communities": {},
            "color": ",".join(
                map(str, hex_to_rgb(self.organization.color if self.organization else settings.DEAD_LEAVES_COLOR))
            ),
            "pic": self.profile_picture.picture.url[1:] if self.profile_picture else "",
            "url": self.telegram_url,
            "activity_period": self.activity_period,
            "fans": self.participants_count,
            "in_deg": self.in_degree,
            "is_lost": self.is_lost,
            "messages_count": self.message_set.count(),
            "out_deg": self.out_degree,
        }
        data.update(default)
        return data

    def save(self, *args: Any, **kwargs: Any) -> None:
        self.username = self.username or ""
        super().save(*args, **kwargs)
        in_degree = (
            Message.objects.filter(channel__organization__is_interesting=True, forwarded_from=self)
            .exclude(channel=self)
            .count()
        )
        out_degree = (
            Message.objects.filter(channel=self, forwarded_from__organization__is_interesting=True)
            .exclude(forwarded_from=self)
            .count()
        )
        Channel.objects.filter(pk=self.pk).update(in_degree=in_degree, out_degree=out_degree)
        self.in_degree = in_degree
        self.out_degree = out_degree


class Message(TelegramBaseModel):
    TELEGRAM_OBJECT_PROPERTIES: ClassVar[tuple[str, ...]] = (
        "date",
        "out",
        "mentioned",
        "post",
        "from_scheduled",
        "message",
        "grouped_id",
        "views",
        "forwards",
        "pinned",
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
    references = models.ManyToManyField(Channel, related_name="reference_message_set")
    missing_references = models.TextField(blank=True)
    grouped_id = models.BigIntegerField(null=True)
    views = models.PositiveBigIntegerField(null=True)
    forwards = models.PositiveBigIntegerField(null=True)
    pinned = models.BooleanField(null=True, default=False)
    has_been_pinned = models.BooleanField(default=False)
    webpage_url = models.URLField(max_length=255, default="", blank=True)
    webpage_type = models.CharField(max_length=255, default="", blank=True)

    def __str__(self) -> str:
        return f"{self.channel.title} [{self.date or self.telegram_id}]"

    def save(self, *args: Any, **kwargs: Any) -> None:
        for field in ("message", "webpage_url", "webpage_type"):
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


class ProfilePicture(TelegramBasePictureModel):
    channel = models.ForeignKey(Channel, on_delete=models.CASCADE)

    def get_media_path(self, filename: str) -> str:
        extension = filename.split(".")[-1]
        return os.path.join(
            "channels",
            self.channel.username,
            "profile",
            f"{self.channel.telegram_id}.{extension}",
        )


class MessagePicture(TelegramBasePictureModel):
    message = models.ForeignKey(Message, on_delete=models.CASCADE)

    def get_media_path(self, filename: str) -> str:
        extension = filename.split(".")[-1]
        return os.path.join(
            "channels",
            self.message.channel.username,
            "message",
            f"{self.message.telegram_id}.{extension}",
        )


class MessageVideo(TelegramBaseModel):
    TELEGRAM_OBJECT_PROPERTIES: ClassVar[tuple[str, ...]] = ("date",)
    message = models.ForeignKey(Message, on_delete=models.CASCADE)
    video = models.FileField(upload_to=_telegram_picture_upload_to_function, max_length=255)
    date = models.DateTimeField(null=True)

    def get_media_path(self, filename: str) -> str:
        extension = filename.split(".")[-1]
        return os.path.join(
            "channels",
            self.message.channel.username,
            "message",
            "video",
            f"{self.message.telegram_id}.{extension}",
        )

    @classmethod
    def from_telegram_object(
        cls, telegram_object: Any, force_update: bool = False, defaults: dict[str, Any] | None = None
    ) -> Self:
        defaults = defaults or {}
        obj = super().from_telegram_object(telegram_object, force_update=force_update, defaults=defaults)
        filename = defaults.get("video", None)
        if filename:
            with open(filename, "rb") as f:
                obj.video.save(os.path.basename(filename), File(f), save=True)
        return obj
