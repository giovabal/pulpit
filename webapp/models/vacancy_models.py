from django.db import models

from webapp.models.base import BaseModel


class ChannelVacancy(BaseModel):
    channel = models.OneToOneField("Channel", on_delete=models.CASCADE, related_name="vacancy")
    death_date = models.DateField()
    note = models.TextField(blank=True)

    class Meta:
        ordering = ["-death_date"]

    def __str__(self) -> str:
        return f"{self.channel} (†{self.death_date})"
