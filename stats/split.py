"""The home page's month-by-month charts split by the labels of one partition group (``?split=<group id>``).

One line per label: the ``SPLIT_MAX_LABELS`` with the most active channels over the charts' whole span, the
remaining labels together, and the posts of channels holding no label of the group. The lines are the same on
every chart of the page, so a label keeps its colour. A label is read at each post's local date
(:class:`network.event_impact.LabelMembership`; a container group through its child labels).
"""

import datetime
from collections import defaultdict
from collections.abc import Iterable
from statistics import median
from typing import Any

from django.db.models import QuerySet

from network.event_impact import LabelMembership
from webapp.models import LabelGroup, Message

#: Labels drawn as lines of their own; the others share one.
SPLIT_MAX_LABELS = 5
#: Active channels a label needs in a month for its median to be drawn: the median of two channels says little.
SPLIT_MIN_CHANNELS = 5

_OTHER = "other"

Line = dict[str, Any]


class LabelSplit:
    """Assigns channel-days to the chart lines of *group* and aggregates them by month over *spine*.

    ``messages`` is the scope's whole queryset, carrying the local ``day`` of each message: it decides which
    labels get a line, whatever subset of it a chart then counts.
    """

    def __init__(self, messages: QuerySet[Message], group: LabelGroup, spine: list[str]) -> None:
        self.spine = spine
        channel_days = list(messages.order_by().values_list("channel_id", "day").distinct())
        self._membership = LabelMembership(sorted({pk for pk, _ in channel_days}), group.pk, group.is_container)
        self._labels: dict[tuple[int, datetime.date], int | None] = {}
        channels: dict[int | None, set[int]] = defaultdict(set)
        for channel_id, day in channel_days:
            channels[self._label(channel_id, day)].add(channel_id)
        names = dict(group.labels.values_list("pk", "name"))
        ranked = sorted((pk for pk in channels if pk is not None), key=lambda pk: (-len(channels[pk]), names[pk]))
        self._shown = set(ranked[:SPLIT_MAX_LABELS])
        self._lines: list[tuple[Any, str, str]] = [(pk, names[pk], "label") for pk in ranked[:SPLIT_MAX_LABELS]]
        if len(ranked) > SPLIT_MAX_LABELS:
            self._lines.append((_OTHER, f"Other ({len(ranked) - SPLIT_MAX_LABELS})", "other"))
        if None in channels:
            self._lines.append((None, f"No {group.name} label", "none"))

    def _label(self, channel_id: int, day: datetime.date) -> int | None:
        key = (channel_id, day)
        if key not in self._labels:
            self._labels[key] = self._membership.at(channel_id, day)
        return self._labels[key]

    def _line_of(self, channel_id: int, day: datetime.date) -> Any:
        label = self._label(channel_id, day)
        return label if label is None or label in self._shown else _OTHER

    def _render(self, values: dict[tuple[Any, str], float], empty: float | None) -> list[Line]:
        return [
            {"label": name, "kind": kind, "values": [values.get((key, month), empty) for month in self.spine]}
            for key, name, kind in self._lines
        ]

    def sums(self, rows: Iterable[tuple[int, datetime.date, float | None]]) -> list[Line]:
        """Lines of monthly totals, from ``(channel, day, value)`` rows."""
        totals: dict[tuple[Any, str], float] = defaultdict(int)
        for channel_id, day, value in rows:
            totals[(self._line_of(channel_id, day), day.strftime("%Y-%m"))] += value or 0
        return self._render(totals, 0)

    def channel_counts(self, rows: Iterable[tuple[int, datetime.date]]) -> list[Line]:
        """Lines of the distinct channels active each month, from ``(channel, day)`` rows."""
        active: dict[tuple[Any, str], set[int]] = defaultdict(set)
        for channel_id, day in rows:
            active[(self._line_of(channel_id, day), day.strftime("%Y-%m"))].add(channel_id)
        return self._render({key: len(channels) for key, channels in active.items()}, 0)

    def medians(self, rows: Iterable[tuple[int, datetime.date, float, float]]) -> list[Line]:
        """Lines of the median channel's monthly ratio, from ``(channel, day, numerator, denominator)`` rows.

        ``None`` where fewer than ``SPLIT_MIN_CHANNELS`` channels have one.
        """
        totals: dict[tuple[Any, str, int], list[float]] = defaultdict(lambda: [0, 0])
        for channel_id, day, numerator, denominator in rows:
            total = totals[(self._line_of(channel_id, day), day.strftime("%Y-%m"), channel_id)]
            total[0] += numerator
            total[1] += denominator
        ratios: dict[tuple[Any, str], list[float]] = defaultdict(list)
        for (line, month, _channel), (numerator, denominator) in totals.items():
            if denominator:
                ratios[(line, month)].append(numerator / denominator)
        return self._render(
            {key: round(median(values), 1) for key, values in ratios.items() if len(values) >= SPLIT_MIN_CHANNELS},
            None,
        )
