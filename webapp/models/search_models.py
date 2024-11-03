from django.db import models

from webapp_engine.models import BaseModel


class SearchTerm(BaseModel):
    word = models.CharField(max_length=255)
    last_check = models.DateTimeField(blank=True, null=True)

    def __str__(self):
        return self.word
