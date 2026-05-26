from django.db import models

from webapp.models import Channel, Message

import pandas as pd


def _month_spine(q: models.Q) -> list[str]:
    """Return a sorted list of YYYY-MM strings spanning the earliest to latest non-lost message matching q."""
    agg = (
        Message.objects.alive()
        .filter(q, date__isnull=False)
        .aggregate(earliest=models.Min("date"), latest=models.Max("date"))
    )
    if not agg["earliest"] or not agg["latest"]:
        return []
    return (
        pd.period_range(
            start=agg["earliest"].strftime("%Y-%m"),
            end=agg["latest"].strftime("%Y-%m"),
            freq="M",
        )
        .strftime("%Y-%m")
        .tolist()
    )


def global_month_spine() -> list[str]:
    """Return a sorted list of all YYYY-MM strings from the earliest to the latest message across in-target channels."""
    from webapp.models import Channel

    in_target_pks = Channel.objects.in_target().values("pk")
    return _month_spine(models.Q(channel__in=in_target_pks))


def channel_month_spine(channel: Channel) -> list[str]:
    """Return a sorted list of all YYYY-MM strings from the channel's first to last message."""
    return _month_spine(models.Q(channel=channel))


def reindex_to_spine(df: "pd.DataFrame", field: str, spine: list[str]) -> "pd.DataFrame":
    """Reindex a month-indexed DataFrame to a full spine, filling missing months with 0."""
    return df.set_index("month").reindex(spine, fill_value=0).reset_index()
