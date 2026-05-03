from django.db import models

from webapp.models.base import BaseModel


class ChannelVacancy(BaseModel):
    channel = models.OneToOneField("Channel", on_delete=models.CASCADE, related_name="vacancy")
    closure_date = models.DateField()
    note = models.TextField(blank=True)

    class Meta:
        ordering = ["-closure_date"]

    def __str__(self) -> str:
        return f"{self.channel} (closed {self.closure_date})"
