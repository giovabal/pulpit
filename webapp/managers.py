from __future__ import annotations

from django.conf import settings
from django.db import models

from webapp.utils.channel_types import channel_type_filter


class ChannelQuerySet(models.QuerySet["Channel"]):
    def interesting(self) -> ChannelQuerySet:
        return (
            self.filter(organization__is_interesting=True)
            .filter(channel_type_filter(settings.DEFAULT_CHANNEL_TYPES))
            .exclude(is_private=True)
        )


class ChannelManager(models.Manager["Channel"]):
    def get_queryset(self) -> ChannelQuerySet:
        return ChannelQuerySet(self.model, using=self._db)

    def interesting(self) -> ChannelQuerySet:
        return self.get_queryset().interesting()
