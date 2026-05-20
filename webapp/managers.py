from __future__ import annotations

from django.conf import settings
from django.db import models

from webapp.utils.channel_types import channel_type_filter


class ChannelQuerySet(models.QuerySet["Channel"]):
    def in_target(self) -> ChannelQuerySet:
        return (
            self.filter(organization__is_in_target=True)
            .filter(channel_type_filter(settings.DEFAULT_CHANNEL_TYPES))
            .exclude(is_private=True)
            .exclude(is_lost=True)
        )


class ChannelManager(models.Manager["Channel"]):
    def get_queryset(self) -> ChannelQuerySet:
        return ChannelQuerySet(self.model, using=self._db)

    def in_target(self) -> ChannelQuerySet:
        return self.get_queryset().in_target()


class MessageQuerySet(models.QuerySet["Message"]):
    def alive(self) -> MessageQuerySet:
        """Exclude messages that no longer exist on Telegram."""
        return self.filter(is_lost=False)


class MessageManager(models.Manager["Message"]):
    def get_queryset(self) -> MessageQuerySet:
        return MessageQuerySet(self.model, using=self._db)

    def alive(self) -> MessageQuerySet:
        return self.get_queryset().alive()
