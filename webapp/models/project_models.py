from typing import Self

from django.db import models

from webapp.models.base import BaseModel


class Project(BaseModel):
    """Single-row project dossier (title + free-text description/criteria/notes).

    The project's identity used to live in `.env` as `PROJECT_TITLE`; it now lives
    here so analysts can edit it (and the accompanying notes) from the Manage panel.
    Enforced as a singleton: `save()` pins the primary key to 1, and `load()` is the
    canonical accessor — it returns the one row, creating it on first access.
    """

    title = models.CharField(max_length=200, blank=True, default="Pulpit project")
    description = models.TextField(blank=True, default="")
    criteria = models.TextField(blank=True, default="")
    notes = models.TextField(blank=True, default="")

    class Meta:
        verbose_name = "Project"
        verbose_name_plural = "Project"

    def __str__(self) -> str:
        return self.title or "Project"

    def save(self, *args, **kwargs) -> None:
        self.pk = 1
        super().save(*args, **kwargs)

    @classmethod
    def load(cls) -> Self:
        obj, _ = cls.objects.get_or_create(pk=1)
        return obj
