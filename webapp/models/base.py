import os
from typing import Any, ClassVar, Self

from django.core.files import File
from django.core.files.storage import FileSystemStorage
from django.db import models

from webapp.utils import is_color_dark

from colorfield.fields import ColorField


class OverwriteStorage(FileSystemStorage):
    """Save to the requested name, overwriting any existing file.

    Default FileSystemStorage adds a random 7-char suffix when the target file
    exists. Media here is keyed deterministically on (channel, message.telegram_id)
    via ``get_media_path``, so a "conflict" always means we're re-downloading the
    same logical media — the suffix would orphan the previous payload and the DB
    would silently drift to point at the suffixed name. Overwrite instead so the
    DB and disk stay in sync.
    """

    def get_available_name(self, name: str, max_length: int | None = None) -> str:
        if self.exists(name):
            self.delete(name)
        return name


class BaseModel(models.Model):
    _created = models.DateTimeField(auto_now_add=True)
    _updated = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True

    @property
    def updated(self) -> Any:
        return self._updated


class BaseColorModel(BaseModel):
    color = ColorField(default="#FF0000")

    class Meta:
        abstract = True

    @property
    def is_color_dark(self) -> bool:
        return is_color_dark(self.color)


class TelegramBaseModel(BaseModel):
    TELEGRAM_OBJECT_PROPERTIES: ClassVar[tuple[str, ...]] = ()
    telegram_id = models.BigIntegerField()

    class Meta:
        abstract = True

    @classmethod
    def _args_for_from_telegram_object(cls, telegram_object: Any) -> dict[str, Any]:
        return {"telegram_id": telegram_object.id if telegram_object else None}

    @classmethod
    def from_telegram_object(
        cls, telegram_object: Any, force_update: bool = True, defaults: dict[str, Any] | None = None
    ) -> Self:
        obj, created = cls.objects.get_or_create(
            **cls._args_for_from_telegram_object(telegram_object), defaults=defaults or {}
        )
        if (created or force_update) and cls.TELEGRAM_OBJECT_PROPERTIES:
            for field in cls.TELEGRAM_OBJECT_PROPERTIES:
                if hasattr(obj, field) and hasattr(telegram_object, field):
                    setattr(obj, field, getattr(telegram_object, field))
            obj.save()
        return obj


def _telegram_picture_upload_to_function(instance: Any, filename: str) -> str:
    return instance.get_media_path(filename)


class TelegramBasePictureModel(TelegramBaseModel):
    TELEGRAM_OBJECT_PROPERTIES: ClassVar[tuple[str, ...]] = ("date",)
    picture = models.ImageField(
        upload_to=_telegram_picture_upload_to_function, storage=OverwriteStorage(), max_length=255
    )
    date = models.DateTimeField(null=True)

    class Meta:
        abstract = True

    def get_media_path(self, filename: str) -> str:
        raise NotImplementedError("define `self.get_media_path()`")

    @classmethod
    def from_telegram_object(
        cls, telegram_object: Any, force_update: bool = False, defaults: dict[str, Any] | None = None
    ) -> Self:
        defaults = defaults or {}
        obj = super().from_telegram_object(telegram_object, force_update=force_update, defaults=defaults)
        filename = defaults.get("picture", None)
        if filename:
            with open(filename, "rb") as f:
                obj.picture.save(os.path.basename(filename), File(f), save=True)
        return obj
