"""The Audience page in a ``structural_analysis`` export (``--audience``, on by default).

The five sections of ``/audience/`` (:mod:`webapp.audience`: participation, breadth, audience overlap,
retention, channels as commenters), computed over the export's date range on its **own** scope instead
of the page's: the graph's observed in-target channels — not the dead leaves nor the
environment, so ``--channel-types``, ``--filter-labels`` and the lost / private switches apply as they
did to the graph — and their posts inside their in-target periods and inside ``--startdate`` /
``--enddate``. Same commenters (Telegram bots and bulk posters left out, Manage → Commenters overrides
as they stand at export time), same statistics, same tables.

With a timeline (``--timeline-step``) each period is computed the same way on its own graph and days
(``data_<key>/audience.json``, ``has_audience`` in ``timeline.json``, per-period workbook columns and sheets);
a period without a reply in scope is left out.

Outputs: ``data/audience.json`` (:func:`compute_audience`'s ``payload``, read by ``audience.html``), the
section CSVs and the ``audience.xlsx`` sheets (:func:`csv_tables`, :func:`xlsx_sheets`, laid out by
:func:`webapp.audience.tables.section_table` like the page's CSVs). Aggregates only: no commenting
account is identified; channels are, as on the page. See docs/audience.md.
"""

from __future__ import annotations

import datetime
from dataclasses import dataclass, field
from typing import Any

from network.utils import GraphData, dead_leaf_ids

import networkx as nx

#: Export file stem of each section's CSV: ``audience_<stem>.csv``.
CSV_STEMS = {
    "participation": "participation",
    "breadth": "breadth",
    "overlap": "overlap",
    "retention": "retention",
    "channel-commenters": "channel_commenters",
}


@dataclass
class AudienceExport:
    """One export's audience: ``sections`` = each section's compute result (model objects, for the
    tables), ``payload`` = the JSON-safe ``data/audience.json``."""

    sections: dict[str, dict[str, Any]]
    payload: dict[str, Any]
    # Channel id → the graph's window-resolved primary label, the label every table of the export shows.
    labels: dict[str, str] = field(default_factory=dict)

    @property
    def has_data(self) -> bool:
        """Whether any reply in scope was found — a person's or a channel's."""
        participation = self.sections.get("participation") or {}
        kinds = (self.sections.get("channel-commenters") or {}).get("kinds") or {}
        return bool((participation.get("overall") or {}).get("accounts") or any(kinds.values()))


def observed_channel_ids(graph: nx.DiGraph) -> frozenset[int]:
    """The graph's observed in-target channels: neither dead leaves nor environment nodes.

    A channel is read from its node data's ``pk`` (``build_graph`` keys nodes by it too); a node without
    a numeric one is not a stored channel and is skipped.
    """
    dead = dead_leaf_ids(graph)
    ids: set[int] = set()
    for node, attrs in graph.nodes(data=True):
        data = attrs.get("data") or {}
        if node in dead or data.get("environment_depth"):
            continue
        pk = str(data.get("pk", node))
        if pk.isdigit():
            ids.add(int(pk))
    return frozenset(ids)


# ── JSON payload ─────────────────────────────────────────────────────────────


class _Refs:
    """Channel references in the payload: ``{"id", "label", "organization"}`` — the graph's own label and
    window-resolved primary label for a node, the stored title for any other channel."""

    def __init__(self, graph_data: GraphData) -> None:
        self._nodes = {str(n["id"]): n for n in graph_data.get("nodes", [])}

    def __call__(self, channel: Any) -> dict[str, Any] | None:
        if channel is None:
            return None
        node = self._nodes.get(str(channel.pk))
        if node is not None:
            return {
                "id": str(channel.pk),
                "label": node.get("label") or channel.title,
                "organization": node.get("organization") or "",
            }
        return {"id": str(channel.pk), "label": channel.title, "organization": ""}


def _day(value: datetime.date | datetime.datetime | None) -> str | None:
    return value.isoformat() if value is not None else None


def _participation(data: dict, ref: _Refs) -> dict:
    from webapp.audience import MIN_CONCENTRATION_COMMENTERS

    overall = dict(data["overall"])
    shares = overall.pop("top_shares")
    overall["top1_share"], overall["top10_share"] = shares[0.01], shares[0.10]
    return {
        "overall": overall,
        "bins": data["bins"],
        "lorenz": data["lorenz"],
        "min_concentration_commenters": MIN_CONCENTRATION_COMMENTERS,
        "channels": [
            {**row, "channel": ref(row["channel"]), "channel_id": str(row["channel_id"])} for row in data["channels"]
        ],
    }


def _breadth(data: dict) -> dict:
    keys = ("accounts", "channel_bins", "multi_channel_share", "channel_spread", "groups")
    return {key: data.get(key) for key in keys}


def _overlap(data: dict, ref: _Refs) -> dict:
    from webapp.audience.tables import pair_heat

    rows = data["channel_rows"]
    pairs = [
        {
            "a": str(pr["a"]),
            "b": str(pr["b"]),
            **{k: pr[k] for k in ("shared", "expected", "ratio", "p", "q", "significant")},
            "heat": pair_heat(pr),
        }
        for pr in data["pairs"]  # the pairs sharing commenters; a matrix cell without one is "·"
    ]
    return {
        "channels": [
            {
                "index": row["index"],
                "channel": ref(row["channel"]),
                "id": str(row["channel_id"]),
                "commenters": row["commenters"],
                "exclusive": row["exclusive"],
            }
            for row in rows
        ],
        "pairs": pairs,
        "tested": data["tested"],
        "validated": data["validated"],
        "q_threshold": data["q_threshold"],
        "label_groups": [
            {
                **group,
                "pairs": [{**pr, "a": str(pr["a"]), "b": str(pr["b"]), "heat": pair_heat(pr)} for pr in group["pairs"]],
            }
            for group in data["label_groups"]
        ],
        "qap": data["qap"],
    }


def _retention(data: dict) -> dict:
    from webapp.audience.tables import cohort_cell

    if not data.get("accounts"):
        return {"accounts": 0}
    return {
        "accounts": data["accounts"],
        "first_day": _day(data["first_day"]),
        "last_day": _day(data["last_day"]),
        "monthly": data["monthly"],
        "returning_share": data["returning_share"],
        "cohorts": [{**c, "cells": [cohort_cell(v) for v in c["cells"]]} for c in data["cohorts"]],
        "cohort_quarters": data["cohort_quarters"],
    }


def _channel_commenters(data: dict, ref: _Refs) -> dict:
    return {
        "pairs": [
            {
                "sender": ref(r["sender"]),
                "sender_tid": r["sender_tid"],
                "sender_name": r["sender_name"],
                "sender_in_target": r["sender_in_target"],
                "channel": ref(r["channel"]),
                "comments": r["comments"],
                "first": _day(r["first"]),
                "last": _day(r["last"]),
                "cited": r["cited"],
            }
            for r in data["pairs"]
        ],
        "kinds": data["kinds"],
        "commenting_channels": data["commenting_channels"],
        "uncited_pairs": data["uncited_pairs"],
    }


def compute_audience(
    graph: nx.DiGraph,
    graph_data: GraphData,
    *,
    start_date: datetime.date | None = None,
    end_date: datetime.date | None = None,
) -> AudienceExport:
    """The five Audience sections over *graph*'s observed in-target channels and the export's dates."""
    from webapp import audience

    scope = audience.Scope(channel_ids=observed_channel_ids(graph), start=start_date, end=end_date)
    sections = {slug: compute(scope) for slug, _title, compute in audience.SECTIONS}
    ref = _Refs(graph_data)
    coverage_keys = ("scope_channels", "channels_with_discussion", "channels_with_comments", "left_out_accounts")
    payload = {
        "coverage": {key: sections["participation"][key] for key in coverage_keys},
        "start_date": _day(start_date),
        "end_date": _day(end_date),
        "participation": _participation(sections["participation"], ref),
        "breadth": _breadth(sections["breadth"]),
        "overlap": _overlap(sections["overlap"], ref),
        "retention": _retention(sections["retention"]),
        "channel_commenters": _channel_commenters(sections["channel-commenters"], ref),
    }
    labels = {str(node["id"]): node.get("organization") or "" for node in graph_data.get("nodes", [])}
    return AudienceExport(sections=sections, payload=payload, labels=labels)


# ── Tables ───────────────────────────────────────────────────────────────────


def csv_tables(result: AudienceExport) -> list[tuple[str, tuple[str, ...], list[list]]]:
    """``[(file name, columns, rows)]`` — each section's main table, as the page's CSV lays it out."""
    from webapp.audience.tables import TABLE_SECTIONS, section_table

    return [
        (
            f"audience_{CSV_STEMS[section]}.csv",
            *_graph_labelled(result, *section_table(section, result.sections[section])),
        )
        for section in TABLE_SECTIONS
    ]


def _graph_labelled(result: AudienceExport, columns: Any, rows: list[list]) -> tuple[Any, list[list]]:
    """A per-channel table with its ``label`` column set to the graph's label of the channel.

    The web app's tables give a channel's *current, directly held* label, which is empty wherever the primary
    label group is a container group; an export shows the label resolved for the analysis window, as its
    channel table and every other sheet do.
    """
    names = list(columns)
    if not result.labels or "channel_id" not in names or "label" not in names:
        return columns, rows
    id_at, label_at = names.index("channel_id"), names.index("label")
    out = []
    for row in rows:
        row = list(row)
        row[label_at] = result.labels.get(str(row[id_at]), row[label_at])
        out.append(row)
    return columns, out


def _summary_rows(payload: dict) -> list[list]:
    coverage = payload["coverage"]
    part = payload["participation"]["overall"]
    hyper = part.get("hyperactive") or {}
    breadth = payload["breadth"]
    spread = breadth.get("channel_spread") or {}
    overlap = payload["overlap"]
    qap = overlap.get("qap") or {}
    retention = payload["retention"]
    commenting = payload["channel_commenters"]
    return [
        ["Channels in scope", coverage["scope_channels"]],
        ["Channels with a discussion group", coverage["channels_with_discussion"]],
        ["Channels with comments", coverage["channels_with_comments"]],
        ["Accounts left out (bots, bulk posters)", coverage["left_out_accounts"]],
        ["From", payload["start_date"]],
        ["To", payload["end_date"]],
        ["Commenters", part["accounts"]],
        ["Replies", part["replies"]],
        ["Replies per commenter (mean)", part["mean"]],
        ["Replies per commenter (median)", part["median"]],
        ["Most active 1% share", part["top1_share"]],
        ["Most active 10% share", part["top10_share"]],
        ["Gini coefficient", part["gini"]],
        ["Effective commenters", part["effective_number"]],
        ["One-time commenters (share of accounts)", part["one_time_share"]],
        ["One-time commenters (share of replies)", part["one_time_reply_share"]],
        ["Hyperactive accounts", hyper.get("accounts")],
        ["Hyperactive accounts (share of replies)", hyper.get("reply_share")],
        ["Hyperactive threshold (replies)", hyper.get("min_replies")],
        ["Commenters on more than one channel (share)", breadth.get("multi_channel_share")],
        ["Channels reached (mean, 2+ replies)", spread.get("observed_mean")],
        ["Channels reached by chance (mean)", spread.get("expected_mean")],
        ["Narrower than chance (share)", spread.get("below_share")],
        ["Channel pairs tested", overlap["tested"]],
        [f"Channel pairs sharing more than chance (q < {overlap['q_threshold']})", overlap["validated"]],
        ["Audience vs citations: r", qap.get("r")],
        ["Audience vs citations: QAP p", qap.get("p")],
        ["Came back (commented in more than one month, share)", retention.get("returning_share")],
        ["Comments on other channels' posts by channels", commenting["kinds"].get("other")],
        ["Channel → channel pairs", len(commenting["pairs"])],
        ["Of which neither cites the other", commenting["uncited_pairs"]],
    ]


# Words of a column name that are not written in lower case in a header.
_HEADER_WORDS = {"id": "ID", "telegram": "Telegram", "a": "A", "b": "B", "gini": "Gini"}
# p- and q-values keep their lower-case symbol, as in every other table.
_SYMBOL_HEADERS = frozenset({"p", "q"})


def _readable(column: str) -> str:
    """A section table's CSV column (``channel_a_id``) as a spreadsheet header (``Channel A ID``): the same
    words, so the header's ``column_key`` is the CSV column again."""
    name = str(column).strip()
    if name in _SYMBOL_HEADERS:
        return name
    words = [_HEADER_WORDS.get(word, word) for word in name.split("_") if word]
    text = " ".join(words)
    return text[:1].upper() + text[1:]


def xlsx_sheets(
    result: AudienceExport, periods: "list[tuple[str, AudienceExport]] | None" = None
) -> list[tuple[str, list[str], list[list]]]:
    """``[(sheet title, headers, rows)]`` for ``audience.xlsx``: a summary, each section's main table (as
    the CSVs, numbers kept numeric) and the tables the page shows beside them.

    With *periods* ``[(period key, its result), …]`` (a timeline export; periods without a reply are left
    out) the summary, the per-channel participation and the overlap pairs hold every period in one table,
    under a leading ``Period`` column (``All periods`` for the full range)."""
    from network.pages import ALL_PERIODS, PERIOD_HEADER
    from webapp.audience.tables import section_table

    payload = result.payload
    periods = periods or []
    # With a timeline, the summary and the per-period tables carry a leading Period column ("All periods" for the
    # full range): every period sits in the same table, as in every workbook of the export.
    scopes: list[tuple[str, AudienceExport]] = [(ALL_PERIODS, result), *periods] if periods else [("", result)]

    def _with_period(headers: list[str], scoped_rows: list[tuple[str, list[list]]]) -> tuple[list[str], list[list]]:
        if not periods:
            return headers, [row for _period, rows in scoped_rows for row in rows]
        return [PERIOD_HEADER, *headers], [[period, *row] for period, rows in scoped_rows for row in rows]

    sheets: list[tuple[str, list[str], list[list]]] = [
        (
            "Summary",
            *_with_period(["Figure", "Value"], [(key, _summary_rows(scoped.payload)) for key, scoped in scopes]),
        )
    ]

    def _table(title: str, section: str, *, per_period: bool = False) -> None:
        section_scopes = scopes if per_period else [scopes[0]]
        columns: list[str] = []
        scoped_rows = []
        for key, scoped in section_scopes:
            cols, rows = _graph_labelled(scoped, *section_table(section, scoped.sections[section], as_text=False))
            columns = [_readable(c) for c in cols]
            scoped_rows.append((key, rows))
        if per_period:
            sheets.append((title, *_with_period(columns, scoped_rows)))
        else:
            sheets.append((title, columns, scoped_rows[0][1]))

    _table("Participation", "participation", per_period=True)
    sheets.append(
        (
            "Activity",
            ["Replies per account", "Accounts", "Share of accounts", "Replies", "Share of replies"],
            [
                [b["label"], b["accounts"], b["account_share"], b["replies"], b["reply_share"]]
                for b in payload["participation"]["bins"]
            ],
        )
    )
    _table("Breadth labels", "breadth")
    spread = payload["breadth"].get("channel_spread") or {}
    sheets.append(
        (
            "Breadth classes",
            ["Replies per account", "Accounts", "Channels reached", "By chance", "Observed / chance", "Below chance"],
            [
                [c["label"], c["accounts"], c["observed"], c["expected"], c["ratio"], c["below_share"]]
                for c in spread.get("classes", [])
            ],
        )
    )
    _table("Overlap pairs", "overlap", per_period=True)
    sheets.append(
        (
            "Overlap channels",
            ["Channel ID", "Channel", "Label", "Commenters", "Exclusive", "Exclusive by chance"],
            [
                [
                    int(c["id"]),
                    (c["channel"] or {}).get("label", ""),
                    (c["channel"] or {}).get("organization", ""),
                    c["commenters"],
                    c["exclusive"].get("observed"),
                    c["exclusive"].get("expected"),
                ]
                for c in payload["overlap"]["channels"]
            ],
        )
    )
    sheets.append(
        (
            "Overlap labels",
            ["Label group", "Label A", "Label B", "Shared", "Expected", "Ratio", "p", "q"],
            [
                [g["name"], pr["name_a"], pr["name_b"], pr["shared"], pr["expected"], pr["ratio"], pr["p"], pr["q"]]
                for g in payload["overlap"]["label_groups"]
                for pr in g["pairs"]
            ],
        )
    )
    _table("Retention by month", "retention")
    retention = payload["retention"]
    quarters = retention.get("cohort_quarters") or []
    sheets.append(
        (
            "Cohorts",
            ["First reply", "Accounts", *[f"+{q}" for q in quarters]],
            [
                [c["quarter"], c["size"], *[cell["value"] if cell else None for cell in c["cells"]]]
                for c in retention.get("cohorts", [])
            ],
        )
    )
    _table("Channel commenters", "channel-commenters")
    return sheets
