from __future__ import annotations

from django.conf import settings
from django.db import models
from django.db.models import Q

from webapp.utils.channel_types import channel_type_filter


class ChannelQuerySet(models.QuerySet["Channel"]):
    def in_target(self) -> ChannelQuerySet:
        return (
            self.filter(
                Q(in_target_override=True) | Q(in_target_override__isnull=True, organization__is_in_target=True)
            )
            .filter(channel_type_filter(settings.DEFAULT_CHANNEL_TYPES))
            .exclude(is_private=True)
            .exclude(is_lost=True)
        )


class ChannelManager(models.Manager["Channel"]):
    def get_queryset(self) -> ChannelQuerySet:
        return ChannelQuerySet(self.model, using=self._db)

    def in_target(self) -> ChannelQuerySet:
        return self.get_queryset().in_target()
