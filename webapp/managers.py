from django.db import models


class ChannelQuerySet(models.QuerySet):
    def interesting(self):
        return self.filter(organization__is_interesting=True)


class ChannelManager(models.Manager):
    def get_queryset(self):
        return ChannelQuerySet(self.model, using=self._db)

    def interesting(self):
        return self.get_queryset().interesting()
