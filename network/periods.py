"""Timeline periods: the snapshots ``structural_analysis --timeline-step`` repeats the export for.

A *step* is the calendar unit the timeline advances by — ``year``, ``quarter`` or ``month``. Without a
window each period is one step (tumbling, non-overlapping periods). With ``--timeline-window N`` each
period is the **trailing** N months ending with a step (a sliding window): ``--timeline-step quarter
--timeline-window 12`` gives one snapshot per quarter, each covering the twelve months up to that
quarter's end. Sliding windows keep every snapshot large enough on sparse data while advancing by a
fine step; their snapshots overlap, so the analyses that need disjoint consecutive periods (temporal
Leiden, the ban replay, RSiena waves) refuse them.

A period's ``key`` names its data directory (``data_<key>/``) and its timeline entry: ``2024``,
``2024Q1``, ``2024-03`` — filesystem-safe, sorting lexicographically in time order, and never a short
number (the compare project lives in ``data_2/``). A sliding window takes the key of the step it ends
with. ``label`` is the display name. Bounds are inclusive local calendar days, the convention of every
``__date`` filter in the pipeline (``network.utils.make_date_q``).
"""

import datetime
from dataclasses import dataclass

from network.parameters import FixedParameter

STEPS: tuple[str, ...] = ("year", "quarter", "month")
STEP_MONTHS: dict[str, int] = {"year": 12, "quarter": 3, "month": 1}
#: Month abbreviations for labels, fixed in English so labels do not depend on the server locale.
_MONTHS = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")

WINDOW_RULE = (
    "trailing windows of N months ending with each step; only windows starting on or after the first step "
    "of the data are kept, so every snapshot spans the same N months (the last one may end early, as the last "
    "step does)"
)

_SOURCE = "network/periods.py"

#: The rules fixed in this module (``PARAMETERS.md``).
FIXED_PARAMETERS: tuple[FixedParameter, ...] = (
    FixedParameter(
        name="Sliding timeline windows",
        value=WINDOW_RULE,
        scope="timeline",
        affects="Which snapshots a --timeline-window run exports and how far back each one reaches.",
        source=f"{_SOURCE}: WINDOW_RULE",
    ),
)


@dataclass(frozen=True)
class Period:
    """One timeline snapshot: ``key`` (directory / JSON id), ``label`` (display), inclusive ``start`` / ``end``
    days, and its ``index`` in the sequence."""

    key: str
    label: str
    start: datetime.date
    end: datetime.date
    index: int

    def as_dict(self) -> dict[str, str]:
        return {"key": self.key, "label": self.label, "start": self.start.isoformat(), "end": self.end.isoformat()}


def validate(step: str, window_months: int | None) -> None:
    """Raise ``ValueError`` for an unknown step or a window that is not a whole multiple (≥ 2) of the step."""
    if step not in STEPS:
        raise ValueError(f"unknown timeline step {step!r}; choose from {', '.join(STEPS)}")
    if window_months:
        months = STEP_MONTHS[step]
        if window_months % months or window_months <= months:
            raise ValueError(
                f"--timeline-window must be a multiple of the step larger than it: {window_months} months does not "
                f"fit a {step} step of {months} month(s)"
            )


def overlapping(step: str, window_months: int | None) -> bool:
    """Whether consecutive snapshots overlap (a sliding window longer than its step)."""
    return bool(window_months) and window_months > STEP_MONTHS[step]


def _add_months(day: datetime.date, months: int) -> datetime.date:
    """The first day of the month ``months`` after ``day``'s month."""
    total = day.year * 12 + (day.month - 1) + months
    return datetime.date(total // 12, total % 12 + 1, 1)


def step_start(day: datetime.date, step: str) -> datetime.date:
    """The first day of the step containing ``day``."""
    months = STEP_MONTHS[step]
    return datetime.date(day.year, (day.month - 1) // months * months + 1, 1)


def step_key(day: datetime.date, step: str) -> str:
    """The key of the step containing ``day`` (``2024``, ``2024Q1``, ``2024-03``)."""
    if step == "year":
        return str(day.year)
    if step == "quarter":
        return f"{day.year}Q{(day.month - 1) // 3 + 1}"
    return f"{day.year}-{day.month:02d}"


def _step_label(day: datetime.date, step: str) -> str:
    if step == "year":
        return str(day.year)
    if step == "quarter":
        return f"{day.year} Q{(day.month - 1) // 3 + 1}"
    return f"{_MONTHS[day.month - 1]} {day.year}"


def build_periods(
    step: str,
    window_months: int | None,
    first_day: datetime.date,
    last_day: datetime.date,
    *,
    clamp_start: datetime.date | None = None,
    clamp_end: datetime.date | None = None,
) -> list[Period]:
    """The timeline periods from the step containing ``first_day`` to the one containing ``last_day``.

    Tumbling (no window): one period per step. Sliding (``window_months``): one trailing window per step
    whose start is not before ``first_day``'s step (module docstring). Bounds are then clamped to the run's
    ``--startdate`` / ``--enddate`` (``clamp_start`` / ``clamp_end``), as the year timeline always did.
    """
    validate(step, window_months)
    months = STEP_MONTHS[step]
    span = window_months or months
    first_step = step_start(first_day, step)
    cursor = step_start(last_day, step)
    steps: list[datetime.date] = []
    while cursor >= first_step:
        steps.append(cursor)
        cursor = _add_months(cursor, -months)
    steps.reverse()
    periods: list[Period] = []
    for begin in steps:
        end = _add_months(begin, months) - datetime.timedelta(days=1)
        start = _add_months(begin, months - span)
        if start < first_step:
            continue  # a window reaching back before the data: not a full snapshot
        if clamp_start and clamp_start > start:
            start = clamp_start
        if clamp_end and clamp_end < end:
            end = clamp_end
        if start > end:
            continue
        if window_months:
            window_end = _add_months(begin, months) - datetime.timedelta(days=1)
            label = f"{_MONTHS[start.month - 1]} {start.year} – {_MONTHS[window_end.month - 1]} {window_end.year}"
        else:
            label = _step_label(begin, step)
        periods.append(Period(key=step_key(begin, step), label=label, start=start, end=end, index=len(periods)))
    return periods


def period_of(periods: list[Period], day: datetime.date) -> Period | None:
    """The tumbling period containing ``day`` (the first one, for overlapping windows), or ``None``."""
    for period in periods:
        if period.start <= day <= period.end:
            return period
    return None
