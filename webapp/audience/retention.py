"""Retention — does the comment audience renew itself or rest on an ageing core (``/audience/retention/``).

* **Monthly series**: accounts active in each month, accounts commenting for the first time, and the
  channels with comments that month — the coverage the other two depend on.
* **Cohorts**: accounts grouped by the quarter of their first reply; for each later quarter, the share
  of the cohort that replied again in it. A cohort quarter not yet over at the data's end is not shown.

A reply's date is its own; replies stored without one take their post's. See docs/audience.md.
"""

from __future__ import annotations

import datetime
from collections import Counter, defaultdict

from network.parameters import FixedParameter

from .scope import Scope, coverage, reply_records

COHORT_QUARTERS = 8

FIXED_PARAMETERS: tuple[FixedParameter, ...] = (
    FixedParameter(
        name="Retention: cohort horizon",
        value=f"{COHORT_QUARTERS} quarters",
        scope="audience",
        affects="How many quarters after its first reply a cohort's return rate is followed.",
        source="webapp/audience/retention.py: COHORT_QUARTERS",
    ),
)


def _month(day: datetime.date) -> str:
    return f"{day.year}-{day.month:02d}"


def _quarter_index(day: datetime.date) -> int:
    return day.year * 4 + (day.month - 1) // 3


def _quarter_label(index: int) -> str:
    return f"{index // 4}Q{index % 4 + 1}"


def _months_between(first: datetime.date, last: datetime.date) -> list[str]:
    out, year, month = [], first.year, first.month
    while (year, month) <= (last.year, last.month):
        out.append(f"{year}-{month:02d}")
        month += 1
        if month > 12:
            year, month = year + 1, 1
    return out


def retention(scope: Scope | None = None) -> dict:
    """Everything the retention section shows, for one scope."""
    replies = [r for r in reply_records(scope) if r.day is not None]
    if not replies:
        return {"accounts": 0, **coverage(scope)}
    first: dict[int, datetime.date] = {}
    last: dict[int, datetime.date] = {}
    months_active: dict[str, set[int]] = defaultdict(set)
    months_channels: dict[str, set[int]] = defaultdict(set)
    quarters_active: dict[int, set[int]] = defaultdict(set)
    for r in replies:
        first[r.sender_id] = min(first.get(r.sender_id, r.day), r.day)
        last[r.sender_id] = max(last.get(r.sender_id, r.day), r.day)
        months_active[_month(r.day)].add(r.sender_id)
        months_channels[_month(r.day)].add(r.channel_id)
        quarters_active[_quarter_index(r.day)].add(r.sender_id)
    start, end = min(first.values()), max(last.values())
    new_by_month = Counter(_month(d) for d in first.values())
    monthly = [
        {
            "month": m,
            "active": len(months_active.get(m, ())),
            "new": new_by_month.get(m, 0),
            "channels": len(months_channels.get(m, ())),
        }
        for m in _months_between(start, end)
    ]

    following = end + datetime.timedelta(days=1)
    quarter_complete = following.day == 1 and following.month % 3 == 1  # end is a quarter's last day
    last_full_quarter = _quarter_index(end) - (0 if quarter_complete else 1)
    cohorts_members: dict[int, set[int]] = defaultdict(set)
    for account, day in first.items():
        cohorts_members[_quarter_index(day)].add(account)
    cohorts = []
    for q in sorted(cohorts_members):
        members = cohorts_members[q]
        cells = []
        for k in range(1, COHORT_QUARTERS + 1):
            if q + k > last_full_quarter:
                cells.append(None)
            else:
                cells.append(len(members & quarters_active.get(q + k, set())) / len(members))
        cohorts.append({"quarter": _quarter_label(q), "size": len(members), "cells": cells})

    return {
        "accounts": len(first),
        "first_day": start,
        "last_day": end,
        "monthly": monthly,
        "returning_share": sum(1 for a in first if _month(first[a]) != _month(last[a])) / len(first),
        "cohorts": cohorts,
        "cohort_quarters": list(range(1, COHORT_QUARTERS + 1)),
        **coverage(scope),
    }
