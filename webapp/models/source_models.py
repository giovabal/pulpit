from django.db import models
from django.utils.text import slugify

from webapp.models.base import BaseModel


class ChannelSource(BaseModel):
    name = models.CharField(max_length=255, unique=True)
    key = models.SlugField(max_length=100, unique=True)
    description = models.TextField(blank=True)
    note = models.TextField(blank=True)
    channels = models.ManyToManyField("Channel", blank=True, related_name="sources")

    class Meta:
        ordering = ["name"]

    def __str__(self) -> str:
        return self.name

    def save(self, *args, **kwargs):
        if not self.key:
            self.key = slugify(self.name)
        super().save(*args, **kwargs)
