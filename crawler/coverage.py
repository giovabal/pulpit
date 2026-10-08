"""Inclusive local-date interval arithmetic for ``Channel.history_coverage``.

An interval is a ``(start, end)`` pair of dates, both inclusive, ``None`` meaning
unbounded on that side. A list of intervals is kept *normalised*: sorted, with
overlapping or adjacent intervals merged and empty ones dropped. The stored JSON
form is ``[[start_iso_or_null, end_iso_or_null], …]``.
"""

import datetime
from collections.abc import Iterable
from typing import Any

Interval = tuple[datetime.date | None, datetime.date | None]

_DAY = datetime.timedelta(days=1)
_MIN = datetime.date.min
_MAX = datetime.date.max


def _bounds(start: datetime.date | None, end: datetime.date | None) -> tuple[datetime.date, datetime.date]:
    return start or _MIN, end or _MAX


def _interval(lo: datetime.date, hi: datetime.date) -> Interval:
    return None if lo == _MIN else lo, None if hi == _MAX else hi


def normalize(intervals: Iterable[Interval]) -> list[Interval]:
    """Sorted, merged (overlapping or day-adjacent intervals fused), empty intervals dropped."""
    spans = sorted(b for b in (_bounds(s, e) for s, e in intervals) if b[0] <= b[1])
    merged: list[tuple[datetime.date, datetime.date]] = []
    for lo, hi in spans:
        if merged and (merged[-1][1] == _MAX or lo <= merged[-1][1] + _DAY):
            merged[-1] = (merged[-1][0], max(merged[-1][1], hi))
        else:
            merged.append((lo, hi))
    return [_interval(lo, hi) for lo, hi in merged]


def union(*parts: Iterable[Interval]) -> list[Interval]:
    return normalize(interval for part in parts for interval in part)


def intersect(a: Iterable[Interval], b: Iterable[Interval]) -> list[Interval]:
    b = [_bounds(s, e) for s, e in normalize(b)]
    pieces = []
    for s, e in normalize(a):
        lo, hi = _bounds(s, e)
        pieces.extend((max(lo, b_lo), min(hi, b_hi)) for b_lo, b_hi in b)
    return normalize(pieces)


def subtract(a: Iterable[Interval], b: Iterable[Interval]) -> list[Interval]:
    """The days of ``a`` not in ``b``."""
    b = [_bounds(s, e) for s, e in normalize(b)]
    pieces: list[tuple[datetime.date, datetime.date]] = []
    for s, e in normalize(a):
        lo, hi = _bounds(s, e)
        left_over = True
        for b_lo, b_hi in b:
            if b_hi < lo:
                continue
            if b_lo > hi:
                break
            if b_lo > lo:
                pieces.append((lo, b_lo - _DAY))
            if b_hi >= hi:
                left_over = False
                break
            lo = b_hi + _DAY
        if left_over:
            pieces.append((lo, hi))
    return normalize(pieces)


def covers(intervals: Iterable[Interval], day: datetime.date) -> bool:
    return any(lo <= day <= hi for lo, hi in (_bounds(s, e) for s, e in intervals))


def to_json(intervals: Iterable[Interval]) -> list[list[str | None]]:
    return [[s.isoformat() if s else None, e.isoformat() if e else None] for s, e in normalize(intervals)]


def from_json(data: Any) -> list[Interval]:
    """Parse the stored JSON form; malformed entries are dropped (a dropped span is simply walked again)."""
    intervals: list[Interval] = []
    for item in data if isinstance(data, list) else ():
        try:
            start, end = item
            intervals.append(
                (
                    None if start is None else datetime.date.fromisoformat(start),
                    None if end is None else datetime.date.fromisoformat(end),
                )
            )
        except (TypeError, ValueError):
            continue
    return normalize(intervals)
