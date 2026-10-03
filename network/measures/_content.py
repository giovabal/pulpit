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


def _near_copy_counts(graph: nx.DiGraph) -> tuple[dict[int, int], dict[int, int]]:
    """Per-channel near-copy counts from the links ``build_graph`` left on ``graph.graph``.

    Returns ``(made, received)``: *made* counts every copying message of a channel (self-copies
    included — a re-post of one's own text is no more original than a self-forward, which
    content originality also counts as forwarded); *received* counts the copies **other**
    channels made of its posts (self-copies excluded, like ``per_channel_forwards_received``).
    Both are empty when near-copy edges are off.
    """
    made: dict[int, int] = {}
    received: dict[int, int] = {}
    for link in graph.graph.get("near_copies") or []:
        made[link.copy_channel_id] = made.get(link.copy_channel_id, 0) + 1
        if not link.is_self_copy:
            received[link.origin_channel_id] = received.get(link.origin_channel_id, 0) + 1
    return made, received


def apply_amplification_factor(
    graph_data: GraphData,
    graph: nx.DiGraph,
    channel_dict: dict[str, Any],
    start_date: datetime.date | None = None,
    end_date: datetime.date | None = None,
    environment_depth: int | None = None,
) -> list[tuple[str, str]]:
    """Add amplification factor (forwards received / own message count) to each node.

    With near-copy edges on, the copies other channels made of a channel's posts count as
    forwards received (``graph.graph["near_copies"]``).
    """
    key = "amplification_factor"

    channel_pks = channel_pks_from_graph_data(graph_data, channel_dict)
    message_counts = per_channel_message_counts(channel_pks, start_date, end_date, environment_depth=environment_depth)
    forwards_received = per_channel_forwards_received(
        channel_pks, start_date, end_date, environment_depth=environment_depth
    )
    _, copies_received = _near_copy_counts(graph)

    for node in graph_data["nodes"]:
        channel_entry = channel_dict.get(node["id"])
        if channel_entry is None:
            continue
        pk = channel_entry["channel"].pk
        mc = message_counts.get(pk, 0)
        fr = forwards_received.get(pk, 0) + copies_received.get(pk, 0)
        node[key] = round(fr / mc, 4) if mc > 0 else 0.0

    return [(key, "Amplification Factor")]


def apply_content_originality(
    graph_data: GraphData,
    graph: nx.DiGraph,
    channel_dict: dict[str, Any],
    start_date: datetime.date | None = None,
    end_date: datetime.date | None = None,
    environment_depth: int | None = None,
) -> list[tuple[str, str]]:
    """Add content originality (1 − forwarded_messages / total_messages) to each node. None if no messages.

    With near-copy edges on, a channel's near-copies (text re-posted without the forward header,
    ``graph.graph["near_copies"]``) count as forwarded messages.
    """
    key = "content_originality"

    channel_pks = channel_pks_from_graph_data(graph_data, channel_dict)
    message_counts = per_channel_message_counts(channel_pks, start_date, end_date, environment_depth=environment_depth)
    forwarded_counts = per_channel_message_counts(
        channel_pks,
        start_date,
        end_date,
        extra_q=Q(forwarded_from__isnull=False),
        environment_depth=environment_depth,
    )
    copies_made, _ = _near_copy_counts(graph)

    for node in graph_data["nodes"]:
        channel_entry = channel_dict.get(node["id"])
        if channel_entry is None:
            continue
        pk = channel_entry["channel"].pk
        mc = message_counts.get(pk, 0)
        not_original = forwarded_counts.get(pk, 0) + copies_made.get(pk, 0)
        node[key] = round(1 - not_original / mc, 4) if mc > 0 else None

    return [(key, "Content Originality")]


def apply_diffusion_lag(
    graph_data: GraphData,
    graph: nx.DiGraph,
    channel_dict: dict[str, Any],
    start_date: datetime.date | None = None,
    end_date: datetime.date | None = None,
    window_days: int = 30,
    environment_depth: int | None = None,
) -> list[tuple[str, str]]:
    """Median hours from original post date to forward date per channel. None if no data.

    window_days: only forwards where lag ≤ window_days are included (0 = no window).
    Uses median to resist anniversary/archival re-shares that would inflate a mean.
    With near-copy edges on, a channel's near-copies of other channels' posts contribute
    their publication lag (copy date − origin date) exactly like forwards.
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
        & channel_cutoff_q(environment_depth=environment_depth)
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
    channel_pk_set = set(channel_pks)
    for link in graph.graph.get("near_copies") or []:
        if link.is_self_copy or link.copy_channel_id not in channel_pk_set:
            continue
        lag_h = link.lag_hours
        if lag_h < 0 or (window_h is not None and lag_h > window_h):
            continue
        accum.setdefault(link.copy_channel_id, []).append(lag_h)

    lag_dict = {pk: round(statistics.median(v), 1) for pk, v in accum.items()}

    for node in graph_data["nodes"]:
        entry = channel_dict.get(node["id"])
        if entry is None:
            continue
        node[key] = lag_dict.get(entry["channel"].pk)

    return [(key, "Diffusion Lag (h)")]
