from django.core.files import File
from django.db import models

from webapp.utils import is_color_dark

from colorfield.fields import ColorField


class BaseModel(models.Model):
    _created = models.DateTimeField(auto_now_add=True)
    _updated = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True

    @property
    def updated(self):
        return self._updated


class BaseColorModel(BaseModel):
    color = ColorField(default="#FF0000")

    class Meta:
        abstract = True

    @property
    def is_color_dark(self):
        return is_color_dark(self.color)


class TelegramBaseModel(BaseModel):
    TELEGRAM_OBJECT_PROPERTIES = ()
    telegram_id = models.BigIntegerField()

    class Meta:
        abstract = True

    @classmethod
    def _args_for_from_telegram_object(cls, telegram_object):
        return {"telegram_id": telegram_object.id if telegram_object else None}

    @classmethod
    def from_telegram_object(cls, telegram_object, force_update=True, defaults=None):
        obj, created = cls.objects.get_or_create(
            **cls._args_for_from_telegram_object(telegram_object), defaults=defaults or {}
        )
        if (created or force_update) and cls.TELEGRAM_OBJECT_PROPERTIES:
            for field in cls.TELEGRAM_OBJECT_PROPERTIES:
                if hasattr(obj, field) and hasattr(telegram_object, field):
                    setattr(obj, field, getattr(telegram_object, field))

            obj.save()

        return obj


def _telegram_picture_upload_to_function(instance, filename):
    return instance.get_media_path(instance, filename)


class TelegramBasePictureModel(TelegramBaseModel):
    TELEGRAM_OBJECT_PROPERTIES = ("date",)
    picture = models.ImageField(upload_to=_telegram_picture_upload_to_function, max_length=255)
    date = models.DateTimeField(null=True)

    class Meta:
        abstract = True

    def get_media_path(self, instance, filename):
        raise NotImplementedError("define `self.get_media_path()`")

    @classmethod
    def from_telegram_object(cls, telegram_object, force_update=False, defaults=None):
        obj = super().from_telegram_object(telegram_object, force_update=force_update, defaults=defaults or {})
        filename = defaults.get("picture", None)
        if filename:
            with open(filename, "rb") as f:
                obj.picture = File(f)
                obj.save(update_fields=("picture",))  # inside 'with', before the file is closed

        return obj
