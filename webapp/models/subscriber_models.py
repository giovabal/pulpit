"""Subscriber history: ``Channel.participants_count`` is overwritten at every crawl, so each crawl that
fetches a channel's details also keeps the count of that day here (one row per channel per local day,
the last crawl of the day winning). Nothing reads the history yet (docs/audience.md § Subscriber history)."""

from django.db import models
from django.utils import timezone


class ChannelSubscriberCount(models.Model):
    channel = models.ForeignKey("Channel", on_delete=models.CASCADE, related_name="subscriber_counts")
    day = models.DateField()
    count = models.PositiveBigIntegerField()

    class Meta:
        constraints = [models.UniqueConstraint(fields=["channel", "day"], name="webapp_subscribercount_unique")]
        ordering = ["channel", "day"]

    def __str__(self) -> str:
        return f"{self.channel_id} on {self.day}: {self.count}"

    @classmethod
    def record(cls, channel, count: int | None) -> None:
        """Keep *count* as *channel*'s subscribers today (nothing when Telegram gave none)."""
        if count is None:
            return
        cls.objects.update_or_create(channel=channel, day=timezone.localdate(), defaults={"count": count})
