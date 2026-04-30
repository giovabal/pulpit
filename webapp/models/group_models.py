from django.db import models

from webapp.models.base import BaseModel


class ChannelGroup(BaseModel):
    name = models.CharField(max_length=255, unique=True)
    description = models.TextField(blank=True)
    note = models.TextField(blank=True)
    channels = models.ManyToManyField("Channel", blank=True, related_name="groups")

    class Meta:
        ordering = ["name"]

    def __str__(self) -> str:
        return self.name
