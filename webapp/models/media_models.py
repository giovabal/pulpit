import os
from typing import Any, ClassVar, Self

from django.core.files import File
from django.db import models

from webapp.models.base import (
    OverwriteStorage,
    TelegramBaseModel,
    TelegramBasePictureModel,
    _telegram_picture_upload_to_function,
)
from webapp.models.telegram_models import Channel, Message


class ProfilePicture(TelegramBasePictureModel):
    channel = models.ForeignKey(Channel, on_delete=models.CASCADE)
    mime_type = models.CharField(max_length=100, blank=True)
    # When ``picture`` is a video avatar (mime_type starts with "video/"),
    # ``thumbnail`` holds the largest static frame so templates can use it as
    # ``<video poster=…>`` or fall back to ``<img>`` when video playback isn't
    # appropriate (e.g. compact channel-list rows).
    thumbnail = models.ImageField(
        upload_to=_telegram_picture_upload_to_function, storage=OverwriteStorage(), max_length=255, blank=True
    )

    def get_media_path(self, filename: str) -> str:
        extension = filename.split(".")[-1]
        channel_dir = self.channel.username or str(self.channel.telegram_id)
        # The photo's own telegram_id keys the filename: a channel has *many*
        # historical profile photos, and a channel-only key would make every row
        # share one file (OverwriteStorage deletes on collision, so the photo
        # downloaded last — the oldest, with Telegram's newest-first iteration —
        # would silently win them all).
        return os.path.join(
            "channels",
            channel_dir,
            "profile",
            f"{self.channel.telegram_id}_{self.telegram_id}.{extension}",
        )

    @property
    def is_video(self) -> bool:
        return bool(self.mime_type and self.mime_type.startswith("video/"))

    @property
    def display_url(self) -> str:
        """Static URL safe to use as ``<img src>``.

        Video avatars return their static thumbnail (empty when none was
        captured); static avatars return the picture itself.
        """
        if self.is_video:
            if self.thumbnail and self.thumbnail.name:
                return self.thumbnail.url
            return ""
        if self.picture:
            return self.picture.url
        return ""

    @classmethod
    def from_telegram_object(
        cls, telegram_object: Any, force_update: bool = False, defaults: dict[str, Any] | None = None
    ) -> Self:
        defaults = defaults or {}
        obj = super().from_telegram_object(telegram_object, force_update=force_update, defaults=defaults)
        mime_type = defaults.get("mime_type")
        if mime_type is not None and obj.mime_type != mime_type:
            obj.mime_type = mime_type
            obj.save(update_fields=["mime_type"])
        thumbnail_filename = defaults.get("thumbnail", None)
        if thumbnail_filename:
            with open(thumbnail_filename, "rb") as f:
                obj.thumbnail.save(os.path.basename(thumbnail_filename), File(f), save=True)
        return obj


class MessagePicture(TelegramBasePictureModel):
    message = models.ForeignKey(Message, on_delete=models.CASCADE)

    class Meta:
        # The same Telegram photo legitimately appears under many Message rows
        # (forwarded posts share photo.id), so identity is (telegram_id,
        # message) — not telegram_id alone. The constraint also pairs with the
        # composite get_or_create lookup in ``_args_for_from_telegram_object``;
        # without it, a race between two concurrent --fix-missing-media calls
        # could create two rows for the same pair.
        constraints = [
            models.UniqueConstraint(fields=["telegram_id", "message"], name="messagepicture_tid_msg_uniq"),
        ]

    @classmethod
    def _args_for_from_telegram_object(
        cls, telegram_object: Any, defaults: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        args = super()._args_for_from_telegram_object(telegram_object, defaults=defaults)
        if defaults and "message" in defaults:
            args["message"] = defaults["message"]
        return args

    def get_media_path(self, filename: str) -> str:
        # Path is keyed on the Telegram photo id, NOT on the recipient
        # Message: a single file is shared by every MessagePicture row that
        # references the same photo (originals + forwards), so disk usage
        # doesn't multiply with each forwarded recovery.
        extension = filename.split(".")[-1]
        return os.path.join("photos", f"{self.telegram_id}.{extension}")


class MessageVideo(TelegramBaseModel):
    TELEGRAM_OBJECT_PROPERTIES: ClassVar[tuple[str, ...]] = ("date",)
    message = models.ForeignKey(Message, on_delete=models.CASCADE)
    video = models.FileField(upload_to=_telegram_picture_upload_to_function, storage=OverwriteStorage(), max_length=255)
    date = models.DateTimeField(null=True)
    is_animated = models.BooleanField(default=False)
    is_round = models.BooleanField(default=False)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["telegram_id", "message"], name="messagevideo_tid_msg_uniq"),
        ]

    @classmethod
    def _args_for_from_telegram_object(
        cls, telegram_object: Any, defaults: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        args = super()._args_for_from_telegram_object(telegram_object, defaults=defaults)
        if defaults and "message" in defaults:
            args["message"] = defaults["message"]
        return args

    def get_media_path(self, filename: str) -> str:
        extension = filename.split(".")[-1]
        return os.path.join("videos", f"{self.telegram_id}.{extension}")

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


class MessageAudio(TelegramBaseModel):
    TELEGRAM_OBJECT_PROPERTIES: ClassVar[tuple[str, ...]] = ("date",)
    message = models.ForeignKey(Message, on_delete=models.CASCADE)
    audio = models.FileField(upload_to=_telegram_picture_upload_to_function, storage=OverwriteStorage(), max_length=255)
    mime_type = models.CharField(max_length=100, blank=True)
    is_voice = models.BooleanField(default=False)
    date = models.DateTimeField(null=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["telegram_id", "message"], name="messageaudio_tid_msg_uniq"),
        ]

    @classmethod
    def _args_for_from_telegram_object(
        cls, telegram_object: Any, defaults: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        args = super()._args_for_from_telegram_object(telegram_object, defaults=defaults)
        if defaults and "message" in defaults:
            args["message"] = defaults["message"]
        return args

    def get_media_path(self, filename: str) -> str:
        extension = filename.split(".")[-1]
        return os.path.join("audios", f"{self.telegram_id}.{extension}")

    @classmethod
    def from_telegram_object(
        cls, telegram_object: Any, force_update: bool = False, defaults: dict[str, Any] | None = None
    ) -> Self:
        defaults = defaults or {}
        obj = super().from_telegram_object(telegram_object, force_update=force_update, defaults=defaults)
        filename = defaults.get("audio", None)
        if filename:
            with open(filename, "rb") as f:
                obj.audio.save(os.path.basename(filename), File(f), save=True)
        return obj


class MessageSticker(TelegramBaseModel):
    TELEGRAM_OBJECT_PROPERTIES: ClassVar[tuple[str, ...]] = ("date",)
    message = models.ForeignKey(Message, on_delete=models.CASCADE)
    sticker = models.FileField(
        upload_to=_telegram_picture_upload_to_function, storage=OverwriteStorage(), max_length=255
    )
    mime_type = models.CharField(max_length=100, blank=True)
    is_animated = models.BooleanField(default=False)
    date = models.DateTimeField(null=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["telegram_id", "message"], name="messagesticker_tid_msg_uniq"),
        ]

    @classmethod
    def _args_for_from_telegram_object(
        cls, telegram_object: Any, defaults: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        args = super()._args_for_from_telegram_object(telegram_object, defaults=defaults)
        if defaults and "message" in defaults:
            args["message"] = defaults["message"]
        return args

    def get_media_path(self, filename: str) -> str:
        extension = filename.split(".")[-1]
        return os.path.join("stickers", f"{self.telegram_id}.{extension}")

    @classmethod
    def from_telegram_object(
        cls, telegram_object: Any, force_update: bool = False, defaults: dict[str, Any] | None = None
    ) -> Self:
        defaults = defaults or {}
        obj = super().from_telegram_object(telegram_object, force_update=force_update, defaults=defaults)
        filename = defaults.get("sticker", None)
        if filename:
            with open(filename, "rb") as f:
                obj.sticker.save(os.path.basename(filename), File(f), save=True)
        return obj


class MessageOtherMedia(TelegramBaseModel):
    TELEGRAM_OBJECT_PROPERTIES: ClassVar[tuple[str, ...]] = ("date",)
    message = models.ForeignKey(Message, on_delete=models.CASCADE)
    media_file = models.FileField(
        upload_to=_telegram_picture_upload_to_function, storage=OverwriteStorage(), max_length=255
    )
    mime_type = models.CharField(max_length=100, blank=True)
    date = models.DateTimeField(null=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["telegram_id", "message"], name="messageothermedia_tid_msg_uniq"),
        ]

    @classmethod
    def _args_for_from_telegram_object(
        cls, telegram_object: Any, defaults: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        args = super()._args_for_from_telegram_object(telegram_object, defaults=defaults)
        if defaults and "message" in defaults:
            args["message"] = defaults["message"]
        return args

    def get_media_path(self, filename: str) -> str:
        extension = filename.split(".")[-1]
        return os.path.join("others", f"{self.telegram_id}.{extension}")

    @classmethod
    def from_telegram_object(
        cls, telegram_object: Any, force_update: bool = False, defaults: dict[str, Any] | None = None
    ) -> Self:
        defaults = defaults or {}
        obj = super().from_telegram_object(telegram_object, force_update=force_update, defaults=defaults)
        filename = defaults.get("media_file", None)
        if filename:
            with open(filename, "rb") as f:
                obj.media_file.save(os.path.basename(filename), File(f), save=True)
        return obj
