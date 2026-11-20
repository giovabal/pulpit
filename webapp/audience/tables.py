"""The Audience sections as tables, shared by the page and the ``structural_analysis`` export.

* :func:`section_table` — each section's main table: the page's ``/audience/<section>.csv``, and the
  export's ``audience_<section>.csv`` and ``audience.xlsx`` sheets (one layout for all three).
* :func:`heat` / :func:`pair_heat` / :func:`cohort_cell` — the tints the overlap matrix and the cohort
  table draw, on the page and in the export's ``audience.html``.
"""

from __future__ import annotations

import math
from collections.abc import Callable
from typing import Any

from webapp.utils.channel_csv import CHANNEL_CSV_COLUMNS, channel_csv_cells

# Diverging cells (shared commenters vs expected): |log2(ratio)| of 2 — four times or a quarter of the
# expectation — reaches the strongest tint, capped so the cell's text stays legible.
HEAT_LOG2_FULL = 2.0
HEAT_MAX_PERCENT = 60
# A pair whose shared and expected commenters are both below this stays untinted: a ratio of 1 to 0.2
# is noise, not overlap.
HEAT_MIN_COUNT = 3
# A cohort cell reaches the strongest tint when this share of the cohort comes back.
COHORT_FULL_SHARE = 0.5

#: The sections with a main table, in menu order (every section has one).
TABLE_SECTIONS = ("participation", "breadth", "overlap", "retention", "channel-commenters")


def heat(ratio: float | None) -> dict[str, Any] | None:
    """A diverging tint for an observed/expected *ratio*: side (``pos``/``neg``) and percent."""
    if ratio is None or ratio <= 0:
        return None
    strength = min(abs(math.log2(ratio)) / HEAT_LOG2_FULL, 1.0)
    return {"side": "pos" if ratio >= 1 else "neg", "percent": round(strength * HEAT_MAX_PERCENT)}


def pair_heat(pair: dict[str, Any]) -> dict[str, Any] | None:
    """The tint of an overlap pair's cell; None for a pair too small to read (:data:`HEAT_MIN_COUNT`)."""
    if not pair["shared"] or max(pair["shared"], pair["expected"]) < HEAT_MIN_COUNT:
        return None
    return heat(pair["ratio"])


def cohort_cell(value: float | None) -> dict[str, Any] | None:
    """A cohort cell: the returning share and its tint percent; None for a quarter not over yet."""
    if value is None:
        return None
    return {"value": value, "percent": round(min(value / COHORT_FULL_SHARE, 1.0) * HEAT_MAX_PERCENT)}


def _text_number(value: float | None) -> str:
    return "" if value is None else f"{value:.6g}"


def _title(channel: Any) -> str:
    return channel.title if channel is not None else ""


def section_table(section: str, data: dict[str, Any], *, as_text: bool = True) -> tuple[tuple[str, ...], list[list]]:
    """The columns and rows of *section*'s main table, from its compute function's *data*.

    ``as_text`` (CSV) writes reals as 6-significant-digit strings and a missing value as ""; without it
    (XLSX) reals stay numbers and a missing value is None. Raises ``KeyError`` for an unknown section.
    """
    num: Callable[[float | None], Any] = _text_number if as_text else (lambda v: v)
    blank: Any = "" if as_text else None
    if section == "participation":
        columns = (
            *CHANNEL_CSV_COLUMNS,
            "subscribers",
            "commenters",
            "replies",
            "replies_per_commenter",
            "commenters_per_subscriber",
            "one_time_share",
            "top10_share",
            "gini",
            "effective_commenters",
            "hyperactive_reply_share",
        )
        rows = [
            [
                row["channel_id"],
                *channel_csv_cells(row["channel"]),
                blank if row["subscribers"] is None else row["subscribers"],
                row["accounts"],
                row["replies"],
                num(row["mean"]),
                num(row["commenter_rate"]),
                num(row["one_time_share"]),
                num(row["top10_share"]),
                num(row["gini"]),
                num(row["effective_number"]),
                num(row["hyperactive_reply_share"]),
            ]
            for row in data["channels"]
        ]
        return columns, rows
    if section == "breadth":
        columns = ("label_group", "label", "commenters", "replies", "commenting_elsewhere_share")
        rows = [
            [g["name"], lab["name"], lab["commenters"], lab["replies"], num(lab["elsewhere_share"])]
            for g in data["groups"]
            for lab in g["labels"]
        ]
        return columns, rows
    if section == "overlap":
        columns = ("channel_a_id", "channel_a", "channel_b_id", "channel_b", "shared", "expected", "ratio", "p", "q")
        rows = [
            [
                pr["a"],
                _title(pr["channel_a"]),
                pr["b"],
                _title(pr["channel_b"]),
                pr["shared"],
                num(pr["expected"]),
                num(pr["ratio"]),
                num(pr["p"]),
                num(pr["q"]),
            ]
            for pr in data["pairs"]
        ]
        return columns, rows
    if section == "retention":
        return ("month", "active_commenters", "new_commenters", "channels_with_comments"), [
            [m["month"], m["active"], m["new"], m["channels"]] for m in data.get("monthly", [])
        ]
    if section == "channel-commenters":
        columns = (
            "commenting_channel_telegram_id",
            "commenting_channel",
            "commenting_in_target",
            "channel_id",
            "channel",
            "comments",
            "first",
            "last",
            "cited_either_way",
        )
        rows = [
            [
                r["sender_tid"],
                _title(r["sender"]) or r["sender_name"],
                int(r["sender_in_target"]),
                r["channel"].pk if r["channel"] else blank,
                _title(r["channel"]),
                r["comments"],
                r["first"].isoformat() if r["first"] else blank,
                r["last"].isoformat() if r["last"] else blank,
                blank if r["cited"] is None else int(r["cited"]),
            ]
            for r in data["pairs"]
        ]
        return columns, rows
    raise KeyError(section)
