from django.core.exceptions import ValidationError
from django.db import models

from webapp.models.base import BaseModel


class ChannelVacancy(BaseModel):
    channel = models.OneToOneField("Channel", on_delete=models.CASCADE, related_name="vacancy")
    closure_date = models.DateField()
    note = models.TextField(blank=True)
    # Analyst-labelled ground truth: the channel known (from qualitative evidence) to
    # have succeeded this vacancy. Optional; when set, the vacancy-analysis export
    # reports each measure's rank of this channel and aggregates hits@k / MRR across
    # labelled vacancies — the validation loop for the succession scores.
    successor = models.ForeignKey(
        "Channel",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="succeeded_vacancies",
    )

    class Meta:
        ordering = ["-closure_date"]

    def clean(self) -> None:
        if self.successor_id and self.successor_id == self.channel_id:
            raise ValidationError({"successor": "A vacancy channel cannot be its own successor."})

    def __str__(self) -> str:
        return f"{self.channel} (closed {self.closure_date})"
