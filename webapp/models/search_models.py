from django.db import models
from django.db.models.functions import Lower

from webapp.models.base import BaseModel


class SearchTerm(BaseModel):
    word = models.CharField(max_length=255)
    last_check = models.DateTimeField(blank=True, null=True)

    class Meta:
        constraints = [
            # DB-level case-insensitive unique index: LOWER(word) must be unique.
            # Python-level save() also lowercases, but this constraint prevents
            # duplicates even when the ORM is bypassed.
            models.UniqueConstraint(Lower("word"), name="search_term_word_lower_unique"),
        ]

    def clean(self) -> None:
        self.word = " ".join(self.word.split()).lower()

    def save(self, *args, **kwargs) -> None:
        self.word = " ".join(self.word.split()).lower()
        super().save(*args, **kwargs)

    def __str__(self) -> str:
        return self.word
