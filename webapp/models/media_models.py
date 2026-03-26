import os
from typing import Any, ClassVar, Self

from django.core.files import File
from django.db import models

from webapp.models.base import TelegramBaseModel, TelegramBasePictureModel, _telegram_picture_upload_to_function
from webapp.models.telegram_models import Channel, Message


class ProfilePicture(TelegramBasePictureModel):
    channel = models.ForeignKey(Channel, on_delete=models.CASCADE)

    def get_media_path(self, filename: str) -> str:
        extension = filename.split(".")[-1]
        channel_dir = self.channel.username or str(self.channel.telegram_id)
        return os.path.join(
            "channels",
            channel_dir,
            "profile",
            f"{self.channel.telegram_id}.{extension}",
        )


class MessagePicture(TelegramBasePictureModel):
    message = models.ForeignKey(Message, on_delete=models.CASCADE)

    def get_media_path(self, filename: str) -> str:
        extension = filename.split(".")[-1]
        channel_dir = self.message.channel.username or str(self.message.channel.telegram_id)
        return os.path.join(
            "channels",
            channel_dir,
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
        channel_dir = self.message.channel.username or str(self.message.channel.telegram_id)
        return os.path.join(
            "channels",
            channel_dir,
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
