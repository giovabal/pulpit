from django.db import models
from django.utils.text import slugify

from webapp.models.base import BaseColorModel


class Organization(BaseColorModel):
    name = models.CharField(max_length=255)
    is_interesting = models.BooleanField(default=True)

    def __str__(self):
        return self.name

    @property
    def key(self):
        return slugify(self.name)
