import filecmp
import os

from django.conf import settings
from django.db import models


class BaseModel(models.Model):
    _created = models.DateTimeField(auto_now_add=True)
    _updated = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True


class TelegramBaseModel(BaseModel):
    TELEGRAM_OBJECT_PROPERTIES = ()
    telegram_id = models.BigIntegerField()

    class Meta:
        abstract = True

    @classmethod
    def _args_for_from_telegram_object(cls, telegram_object):
        return {"telegram_id": telegram_object.id}

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


class TelegramBasePictureModel(TelegramBaseModel):
    TELEGRAM_OBJECT_PROPERTIES = ("date",)
    picture = models.ImageField(upload_to="", max_length=255)
    date = models.DateTimeField(null=True)

    class Meta:
        abstract = True

    def channel_media_path(self, filename):
        raise NotImplementedError("define `self.channel_media_path()`")

    def is_already_downloaded(self, old_filename, new_filename):
        return os.path.isfile(new_filename) and filecmp.cmp(old_filename, new_filename)

    @classmethod
    def from_telegram_object(cls, telegram_object, force_update=False, defaults=None):
        obj = super().from_telegram_object(telegram_object, force_update=force_update, defaults=defaults or {})
        filename = defaults.get("picture", None)
        if not filename:
            return obj

        old_filename = os.path.join(settings.BASE_DIR, filename)
        new_filename = os.path.join(settings.MEDIA_ROOT, obj.channel_media_path(filename))
        if not os.path.exists(new_filename):
            newdir_chunks = os.path.split(new_filename)[:-1]
            newdir = os.path.join(*newdir_chunks)
            os.makedirs(newdir, exist_ok=True)

        if obj.is_already_downloaded(old_filename, new_filename):
            os.remove(old_filename)
            return obj

        os.rename(old_filename, new_filename)
        obj.picture = new_filename
        obj.save(update_fields=("picture",))
