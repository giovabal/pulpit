from __future__ import annotations

from django.db import models


class ChannelQuerySet(models.QuerySet["Channel"]):
    def interesting(self) -> ChannelQuerySet:
        return self.filter(organization__is_interesting=True, is_user_account=False)


class ChannelManager(models.Manager["Channel"]):
    def get_queryset(self) -> ChannelQuerySet:
        return ChannelQuerySet(self.model, using=self._db)

    def interesting(self) -> ChannelQuerySet:
        return self.get_queryset().interesting()
