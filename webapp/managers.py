from __future__ import annotations

import datetime

from django.conf import settings
from django.db import models
from django.db.models import Exists, OuterRef, Q

from webapp.utils.channel_types import channel_type_filter


class ChannelQuerySet(models.QuerySet["Channel"]):
    def in_target(self) -> ChannelQuerySet:
        """Channels with at least one in-target attribution period (any time)."""
        from webapp.models import ChannelAttribution

        has_in_target = ChannelAttribution.objects.filter(channel=OuterRef("pk"), organization__is_in_target=True)
        return (
            self.filter(Exists(has_in_target))
            .filter(channel_type_filter(settings.DEFAULT_CHANNEL_TYPES))
            .exclude(is_private=True)
            .exclude(is_lost=True)
        )

    def in_target_in_window(self, start_date: datetime.date | None, end_date: datetime.date | None) -> ChannelQuerySet:
        """Channels with an in-target period overlapping the inclusive window [start_date, end_date]."""
        from webapp.models import ChannelAttribution

        sub = ChannelAttribution.objects.filter(channel=OuterRef("pk"), organization__is_in_target=True)
        if end_date is not None:
            sub = sub.filter(Q(start__isnull=True) | Q(start__lte=end_date))
        if start_date is not None:
            sub = sub.filter(Q(end__isnull=True) | Q(end__gte=start_date))
        return (
            self.filter(Exists(sub))
            .filter(channel_type_filter(settings.DEFAULT_CHANNEL_TYPES))
            .exclude(is_private=True)
            .exclude(is_lost=True)
        )


class ChannelManager(models.Manager["Channel"]):
    def get_queryset(self) -> ChannelQuerySet:
        return ChannelQuerySet(self.model, using=self._db)

    def in_target(self) -> ChannelQuerySet:
        return self.get_queryset().in_target()

    def in_target_in_window(self, start_date: datetime.date | None, end_date: datetime.date | None) -> ChannelQuerySet:
        return self.get_queryset().in_target_in_window(start_date, end_date)


class MessageQuerySet(models.QuerySet["Message"]):
    def alive(self) -> MessageQuerySet:
        """Exclude messages that no longer exist on Telegram."""
        return self.filter(is_lost=False)


class MessageManager(models.Manager["Message"]):
    def get_queryset(self) -> MessageQuerySet:
        return MessageQuerySet(self.model, using=self._db)

    def alive(self) -> MessageQuerySet:
        return self.get_queryset().alive()
