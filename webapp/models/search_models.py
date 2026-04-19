from django.db import models

from webapp.models.base import BaseModel


class SearchTerm(BaseModel):
    word = models.CharField(max_length=255, unique=True)
    last_check = models.DateTimeField(blank=True, null=True)

    def clean(self) -> None:
        self.word = " ".join(self.word.split()).lower()

    def save(self, *args, **kwargs) -> None:
        self.word = " ".join(self.word.split()).lower()
        super().save(*args, **kwargs)

    def __str__(self) -> str:
        return self.word
