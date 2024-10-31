from django.db import models

from webapp_engine.models import BaseModel

from colorfield.fields import ColorField


class Organization(BaseModel):
    name = models.CharField(max_length=255)
    color = ColorField(default="#FF0000")
    is_interesting = models.BooleanField(default=True)

    def __str__(self):
        return self.name


class Category(BaseModel):
    name = models.CharField(max_length=255)
    color = ColorField(default="#FF0000")

    class Meta:
        verbose_name_plural = "Categories"

    def __str__(self):
        return self.name
