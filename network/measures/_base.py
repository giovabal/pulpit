import datetime
import logging
from math import log
from typing import Any

from django.db.models import Count, Max, Min, Q

from network.utils import GraphData, channel_cutoff_q, make_date_q
from webapp.models import Message

import networkx as nx

logger = logging.getLogger(__name__)


def channel_pks_from_graph_data(graph_data: GraphData, channel_dict: dict[str, Any]) -> list[int]:
    """PKs of the Channels represented as nodes in ``graph_data`` (in graph order)."""
    return [channel_dict[node["id"]]["channel"].pk for node in graph_data["nodes"] if channel_dict.get(node["id"])]


def apply_measure(
    graph_data: GraphData,
    values: dict[str, float],
    key: str,
    label: str,
    *,
    default: Any = 0.0,
) -> list[tuple[str, str]]:
    """Write a per-node scalar onto every node in ``graph_data``.

    Used by the simple measure-application functions in ``_centrality`` and
    ``_spreading`` whose only varying bit was the values dict, the key name,
    and the label — the surrounding ``for node in graph_data["nodes"]: ...``
    loop was repeated identically a dozen times. Nodes absent from
    ``values`` receive ``default``.
    """
    for node in graph_data["nodes"]:
        node[key] = values.get(node["id"], default)
    return [(key, label)]


def compute_neighbour_community_entropy(
    graph: nx.DiGraph,
    partition: dict[Any, Any],
) -> dict[Any, float]:
    """Shannon entropy of the community distribution among each node's
    weighted neighbours (predecessors ∪ successors). The bridging-
    centrality recipe multiplies this by betweenness to surface broker
    nodes — high entropy = node bridges many distinct communities.

    Shared by :func:`network.measures._centrality.apply_bridging_centrality`
    and :func:`network.robustness.attacks._bridging_with_partition`, which
    used to carry independent copies of the same formula.

    Nodes absent from ``partition``: their edges are skipped (treated as
    "unknown community", contributing nothing to the entropy). Nodes with
    no community-tagged neighbours, or all neighbours in one community,
    receive 0.0.
    """
    entropies: dict[Any, float] = {}
    for node in graph.nodes():
        weights: dict[Any, float] = {}
        for pred in graph.predecessors(node):
            w = graph.edges[pred, node].get("weight", 1.0)
            c = partition.get(pred)
            if c is not None:
                weights[c] = weights.get(c, 0.0) + w
        for succ in graph.successors(node):
            w = graph.edges[node, succ].get("weight", 1.0)
            c = partition.get(succ)
            if c is not None:
                weights[c] = weights.get(c, 0.0) + w
        total = sum(weights.values())
        if total == 0.0 or len(weights) <= 1:
            entropies[node] = 0.0
        else:
            entropies[node] = -sum((w / total) * log(w / total) for w in weights.values())
    return entropies


def per_channel_message_counts(
    channel_pks: list[int],
    start_date: datetime.date | None,
    end_date: datetime.date | None,
    *,
    alive: bool = True,
    extra_q: Q | None = None,
) -> dict[int, int]:
    """Return ``{channel_id: count}`` of messages in ``channel_pks`` honouring the
    date window and each channel's ``out_of_target_after`` cutoff.

    ``alive``: when True (default), excludes messages marked as lost. Base node
    measures pass ``alive=False`` to keep parity with historical totals.
    ``extra_q``: optional Q filter merged with the base query (e.g. for
    forwarded-only sub-counts).
    """
    msg_q = Q(channel_id__in=channel_pks) & make_date_q(start_date, end_date) & channel_cutoff_q()
    if extra_q is not None:
        msg_q &= extra_q
    qs = Message.objects.alive() if alive else Message.objects
    return {
        item["channel_id"]: item["total"] for item in qs.filter(msg_q).values("channel_id").annotate(total=Count("id"))
    }


def per_channel_forwards_received(
    channel_pks: list[int],
    start_date: datetime.date | None,
    end_date: datetime.date | None,
) -> dict[int, int]:
    """Return ``{channel_id: count_of_messages_in_other_in_target_channels_forwarding_from_it}``."""
    fwd_q = (
        Q(forwarded_from_id__in=channel_pks, channel_id__in=channel_pks)
        & make_date_q(start_date, end_date)
        & channel_cutoff_q()
    )
    return {
        item["forwarded_from_id"]: item["total"]
        for item in Message.objects.alive().filter(fwd_q).values("forwarded_from_id").annotate(total=Count("id"))
    }


def apply_base_node_measures(
    graph_data: GraphData,
    graph: nx.DiGraph,
    channel_dict: dict[str, Any],
    start_date: datetime.date | None = None,
    end_date: datetime.date | None = None,
) -> list[tuple[str, str]]:
    """Populate degree, fans, message count, and activity period on each node."""
    measures_labels: list[tuple[str, str]] = [
        ("in_deg", "Inbound connections"),
        ("out_deg", "Outbound connections"),
        ("fans", "Users"),
        ("messages_count", "Messages"),
    ]

    channel_pks = channel_pks_from_graph_data(graph_data, channel_dict)
    # Base totals historically include lost messages (alive=False).
    message_counts = per_channel_message_counts(channel_pks, start_date, end_date, alive=False)
    # Activity bounds need Min/Max aggregates, not the per-channel count shape.
    msg_q = Q(channel_id__in=channel_pks) & make_date_q(start_date, end_date) & channel_cutoff_q()
    activity_bounds: dict[int, dict] = {
        item["channel_id"]: {"min_date": item["min_date"], "max_date": item["max_date"]}
        for item in Message.objects.filter(msg_q, date__isnull=False)
        .values("channel_id")
        .annotate(min_date=Min("date"), max_date=Max("date"))
    }

    now = datetime.datetime.now(datetime.timezone.utc)
    date_template = "%b %Y"
    for node in graph_data["nodes"]:
        channel_entry = channel_dict.get(node["id"])
        if channel_entry is None:
            continue
        channel = channel_entry["channel"]
        node["in_deg"] = graph.in_degree(node["id"], weight="weight")
        node["out_deg"] = graph.out_degree(node["id"], weight="weight")
        node["fans"] = channel.participants_count
        node["messages_count"] = message_counts.get(channel.pk, 0)
        node["label"] = channel.title
        agg = activity_bounds.get(channel.pk, {})
        first_date, last_date = agg.get("min_date"), agg.get("max_date")
        start_candidates = [d for d in (channel.date, first_date) if d is not None]
        end_candidates = [d for d in (channel.date, last_date) if d is not None]
        start = min(start_candidates) if start_candidates else None
        end = max(end_candidates) if end_candidates else None
        if start is None or end is None:
            node["activity_period"] = "Unknown"
            node["activity_start"] = ""
            node["activity_end"] = ""
        else:
            node["activity_period"] = (
                f"{start.strftime(date_template)} - {end.strftime(date_template)}"
                if end < now - datetime.timedelta(days=30)
                else f"{start.strftime(date_template)} - "
            )
            node["activity_start"] = start.strftime("%Y-%m")
            node["activity_end"] = end.strftime("%Y-%m")
    return measures_labels
