"""The home page split by the labels of one partition group (``?split=<group id>``): its month-by-month charts
(``stats.views``) and its summary cards (``webapp.home_split``).

One line per label: the ``SPLIT_MAX_LABELS`` with the most active channels over the charts' whole span, the
remaining labels together, and the posts of channels holding no label of the group. The lines are the same on
every chart and card of the page, so a label keeps its colour. A label is read at each post's local date
(:class:`network.event_impact.LabelMembership`; a container group through its child labels).
"""

import datetime
from collections import defaultdict
from collections.abc import Iterable, Sequence
from statistics import median
from typing import Any

from django.db.models import QuerySet
from django.utils import timezone

from network.event_impact import LabelMembership
from webapp.models import LabelGroup, Message

#: Labels drawn as lines of their own; the others share one.
SPLIT_MAX_LABELS = 5
#: Active channels a label needs in a month for its median to be drawn: the median of two channels says little.
SPLIT_MIN_CHANNELS = 5

_OTHER = "other"

Line = dict[str, Any]


class LabelSplit:
    """Assigns channel-days to the lines of *group*; the charts' monthly aggregates run over *spine*.

    ``messages`` is the scope's whole queryset, carrying the local ``day`` of each message: it decides which
    labels get a line, whatever subset of it a chart then counts. ``channel_ids`` — the channels whose labels
    are needed, when they are more than the ones in ``messages`` (the cards count channels that never posted).
    """

    def __init__(
        self,
        messages: QuerySet[Message],
        group: LabelGroup,
        spine: Sequence[str] = (),
        channel_ids: Iterable[int] | None = None,
    ) -> None:
        self.spine = spine
        self._group = group
        posting = set(messages.order_by().values_list("channel_id", flat=True).distinct())
        self._membership = LabelMembership(sorted(posting.union(channel_ids or ())), group.pk, group.is_container)
        #: Channels whose label depends on the day (a period with a start or an end); the others' does not.
        self.changing: set[int] = {
            channel_id
            for cache, _parents in self._membership.caches
            for channel_id, periods in cache.items()
            if any(start is not None or end is not None for _label, start, end in periods)
        }
        self._labels: dict[tuple[int, datetime.date | None], int | None] = {}
        channels: dict[int | None, set[int]] = defaultdict(set)
        for channel_id in posting - self.changing:
            channels[self._label(channel_id, None)].add(channel_id)
        if self.changing:
            days = messages.filter(channel_id__in=self.changing).order_by().values_list("channel_id", "day").distinct()
            for channel_id, day in days:
                channels[self._label(channel_id, day)].add(channel_id)
        names = dict(group.labels.values_list("pk", "name"))
        ranked = sorted((pk for pk in channels if pk is not None), key=lambda pk: (-len(channels[pk]), names[pk]))
        self._shown = set(ranked[:SPLIT_MAX_LABELS])
        self._lines: list[tuple[Any, str, str]] = [(pk, names[pk], "label") for pk in ranked[:SPLIT_MAX_LABELS]]
        if len(ranked) > SPLIT_MAX_LABELS:
            self._lines.append((_OTHER, f"Other ({len(ranked) - SPLIT_MAX_LABELS})", "other"))
        if None in channels:
            self._lines.append((None, f"No {group.name} label", "none"))

    def _label(self, channel_id: int, day: datetime.date | None) -> int | None:
        if channel_id not in self.changing:
            day = None
        key = (channel_id, day)
        if key not in self._labels:
            undated = day is None and channel_id in self.changing
            self._labels[key] = None if undated else self._membership.at(channel_id, day or datetime.date.min)
        return self._labels[key]

    def _line_for(self, label: int | None) -> Any:
        return label if label is None or label in self._shown else _OTHER

    def line_of(self, channel_id: int, day: datetime.date | None) -> Any:
        """The line of a channel's post of *day* (``None`` will do for a channel not in ``changing``)."""
        return self._line_for(self._label(channel_id, day))

    def channel_line(self, channel_id: int) -> Any:
        """The line a channel itself counts under: its label today, else its latest past one, else its earliest
        (``Channel.representative_label``)."""
        today = timezone.localdate()
        for cache, parent_of in self._membership.caches:
            periods = cache.get(channel_id)
            if not periods:
                continue
            past = [period for period in periods if period[2] is not None and period[2] < today]
            current = [p for p in periods if (p[1] is None or p[1] <= today) and (p[2] is None or p[2] >= today)]
            chosen = current[0] if current else max(past, key=lambda p: p[2]) if past else periods[0]
            return self._line_for(parent_of.get(chosen[0]) if parent_of is not None else chosen[0])
        return None

    def lines(self, used: Iterable[Any] = ()) -> list[tuple[Any, str, str]]:
        """The ``(line, name, kind)`` in order, with the *used* lines no in-scope post called for."""
        lines, known, used = list(self._lines), {key for key, _name, _kind in self._lines}, set(used)
        if _OTHER in used - known:
            at = len(lines) - (None in known)
            lines.insert(at, (_OTHER, "Other", "other"))
        if None in used - known:
            lines.append((None, f"No {self._group.name} label", "none"))
        return lines

    def _render(self, values: dict[tuple[Any, str], float], empty: float | None) -> list[Line]:
        return [
            {"label": name, "kind": kind, "values": [values.get((key, month), empty) for month in self.spine]}
            for key, name, kind in self._lines
        ]

    def sums(self, rows: Iterable[tuple[int, datetime.date, float | None]]) -> list[Line]:
        """Lines of monthly totals, from ``(channel, day, value)`` rows."""
        totals: dict[tuple[Any, str], float] = defaultdict(int)
        for channel_id, day, value in rows:
            totals[(self.line_of(channel_id, day), day.strftime("%Y-%m"))] += value or 0
        return self._render(totals, 0)

    def channel_counts(self, rows: Iterable[tuple[int, datetime.date]]) -> list[Line]:
        """Lines of the distinct channels active each month, from ``(channel, day)`` rows."""
        active: dict[tuple[Any, str], set[int]] = defaultdict(set)
        for channel_id, day in rows:
            active[(self.line_of(channel_id, day), day.strftime("%Y-%m"))].add(channel_id)
        return self._render({key: len(channels) for key, channels in active.items()}, 0)

    def medians(self, rows: Iterable[tuple[int, datetime.date, float, float]]) -> list[Line]:
        """Lines of the median channel's monthly ratio, from ``(channel, day, numerator, denominator)`` rows.

        ``None`` where fewer than ``SPLIT_MIN_CHANNELS`` channels have one.
        """
        totals: dict[tuple[Any, str, int], list[float]] = defaultdict(lambda: [0, 0])
        for channel_id, day, numerator, denominator in rows:
            total = totals[(self.line_of(channel_id, day), day.strftime("%Y-%m"), channel_id)]
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
