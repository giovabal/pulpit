from django.db import models

from webapp_engine.models import BaseColorModel


class Organization(BaseColorModel):
    name = models.CharField(max_length=255)
    is_interesting = models.BooleanField(default=True)

    def __str__(self):
        return self.name


class Category(BaseColorModel):
    name = models.CharField(max_length=255)

    class Meta:
        verbose_name_plural = "Categories"

    def __str__(self):
        return self.name
