import datetime
import statistics
from typing import Any

from django.db.models import F, Q

from network.measures._base import (
    channel_pks_from_graph_data,
    per_channel_forwards_received,
    per_channel_message_counts,
)
from network.utils import GraphData, channel_cutoff_q, make_date_q
from webapp.models import Message

import networkx as nx


def apply_amplification_factor(
    graph_data: GraphData,
    graph: nx.DiGraph,
    channel_dict: dict[str, Any],
    start_date: datetime.date | None = None,
    end_date: datetime.date | None = None,
) -> list[tuple[str, str]]:
    """Add amplification factor (forwards received / own message count) to each node."""
    key = "amplification_factor"

    channel_pks = channel_pks_from_graph_data(graph_data, channel_dict)
    message_counts = per_channel_message_counts(channel_pks, start_date, end_date)
    forwards_received = per_channel_forwards_received(channel_pks, start_date, end_date)

    for node in graph_data["nodes"]:
        channel_entry = channel_dict.get(node["id"])
        if channel_entry is None:
            continue
        pk = channel_entry["channel"].pk
        mc = message_counts.get(pk, 0)
        fr = forwards_received.get(pk, 0)
        node[key] = round(fr / mc, 4) if mc > 0 else 0.0

    return [(key, "Amplification Factor")]


def apply_content_originality(
    graph_data: GraphData,
    graph: nx.DiGraph,
    channel_dict: dict[str, Any],
    start_date: datetime.date | None = None,
    end_date: datetime.date | None = None,
) -> list[tuple[str, str]]:
    """Add content originality (1 − forwarded_messages / total_messages) to each node. None if no messages."""
    key = "content_originality"

    channel_pks = channel_pks_from_graph_data(graph_data, channel_dict)
    message_counts = per_channel_message_counts(channel_pks, start_date, end_date)
    forwarded_counts = per_channel_message_counts(
        channel_pks, start_date, end_date, extra_q=Q(forwarded_from__isnull=False)
    )

    for node in graph_data["nodes"]:
        channel_entry = channel_dict.get(node["id"])
        if channel_entry is None:
            continue
        pk = channel_entry["channel"].pk
        mc = message_counts.get(pk, 0)
        node[key] = round(1 - forwarded_counts.get(pk, 0) / mc, 4) if mc > 0 else None

    return [(key, "Content Originality")]


def apply_diffusion_lag(
    graph_data: GraphData,
    graph: nx.DiGraph,
    channel_dict: dict[str, Any],
    start_date: datetime.date | None = None,
    end_date: datetime.date | None = None,
    window_days: int = 30,
) -> list[tuple[str, str]]:
    """Median hours from original post date to forward date per channel. None if no data.

    window_days: only forwards where lag ≤ window_days are included (0 = no window).
    Uses median to resist anniversary/archival re-shares that would inflate a mean.
    """
    key = "diffusion_lag"
    channel_pks = channel_pks_from_graph_data(graph_data, channel_dict)
    # ~Q(channel=forwarded_from): archival re-shares of one's *own* posts measure
    # nothing about reaction speed to external content and would skew the median.
    fwd_q = (
        Q(channel_id__in=channel_pks)
        & Q(forwarded_from__isnull=False)
        & ~Q(channel_id=F("forwarded_from_id"))
        & Q(fwd_from_date__isnull=False)
        & Q(date__isnull=False)
        & make_date_q(start_date, end_date)
        & channel_cutoff_q()
    )
    window_h = window_days * 24 if window_days > 0 else None
    accum: dict[int, list[float]] = {}
    for row in Message.objects.alive().filter(fwd_q).values("channel_id", "date", "fwd_from_date").iterator():
        lag_h = (row["date"] - row["fwd_from_date"]).total_seconds() / 3600
        if lag_h < 0:
            continue
        if window_h is not None and lag_h > window_h:
            continue
        accum.setdefault(row["channel_id"], []).append(lag_h)

    lag_dict = {pk: round(statistics.median(v), 1) for pk, v in accum.items()}

    for node in graph_data["nodes"]:
        entry = channel_dict.get(node["id"])
        if entry is None:
            continue
        node[key] = lag_dict.get(entry["channel"].pk)

    return [(key, "Diffusion Lag (h)")]
