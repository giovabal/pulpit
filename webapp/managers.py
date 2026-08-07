from __future__ import annotations

from django.conf import settings
from django.db import models
from django.db.models import Exists, OuterRef

from webapp.utils.channel_types import channel_type_filter


class ChannelQuerySet(models.QuerySet["Channel"]):
    def in_target(self) -> ChannelQuerySet:
        """Channels holding at least one in-target label (any period)."""
        from webapp.models import ChannelLabel

        has_in_target = ChannelLabel.objects.filter(channel=OuterRef("pk"), label__is_in_target=True)
        return (
            self.filter(Exists(has_in_target))
            .filter(channel_type_filter(settings.DEFAULT_CHANNEL_TYPES))
            .exclude(is_private=True)
            .exclude(is_lost=True)
        )

    def in_container_label(self, voice) -> ChannelQuerySet:
        """Channels holding any child label of ``voice`` (a container-group label).

        Container labels are purely structural — never linked to channels
        directly — so the scope is exactly the channels of the labels assigned
        under the voice (one hop — child links are not followed transitively).
        "Any period" semantics, matching :meth:`in_target`: a channel counts as
        e.g. "Europe" if any of its label periods carries a Europe-assigned label.
        """
        from webapp.models import ChannelLabel

        holds_child = ChannelLabel.objects.filter(channel=OuterRef("pk"), label__parent_links__parent=voice)
        return self.filter(Exists(holds_child))


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
