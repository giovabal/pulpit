from django.db import models

from colorfield.fields import ColorField


class EventType(models.Model):
    name = models.CharField(max_length=200)
    description = models.TextField(blank=True)
    color = ColorField(default="#ff0000")

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name


class Event(models.Model):
    date = models.DateField()
    subject = models.CharField(max_length=500)
    action = models.ForeignKey(EventType, on_delete=models.PROTECT, related_name="events")
    # The part of the network the event concerns — e.g. a national ban scoped to Nation: Germany. Empty =
    # the whole network. A scoped event's impact is tested as a comparative interrupted time series: the
    # channels holding one of these labels at the date against the others (network.event_impact).
    labels = models.ManyToManyField("webapp.Label", blank=True, related_name="events")

    class Meta:
        ordering = ["-date"]

    def __str__(self):
        return f"{self.date} — {self.subject}"
