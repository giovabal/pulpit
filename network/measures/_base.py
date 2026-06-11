import datetime
import logging
from typing import Any

from django.db.models import Count, F, Max, Min, Q

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


def compute_neighbour_community_participation(
    graph: nx.DiGraph,
    partition: dict[Any, Any],
) -> dict[Any, float]:
    """Participation coefficient (Guimerà & Amaral, *Nature* 2005) of each node
    over the community distribution of its weighted neighbours (predecessors ∪
    successors):

        ``P(v) = 1 − Σ_c (w_c / W)²``

    where ``w_c`` is the total edge weight from ``v`` to community ``c`` and ``W``
    the total neighbour weight. ``P`` is 0 when every neighbour sits in a single
    community (no bridging) and approaches 1 as ``v``'s ties spread evenly across
    many communities — the canonical community-role quantity, bounded in ``[0, 1]``.

    Used by :func:`network.measures._centrality.apply_module_role` as the P axis
    of the Guimerà & Amaral within-module-role plane.

    Nodes absent from ``partition``: their edges are skipped (treated as
    "unknown community", contributing nothing). Nodes with no community-tagged
    neighbours, or all neighbours in one community, receive 0.0.
    """
    participation: dict[Any, float] = {}
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
            participation[node] = 0.0
        else:
            participation[node] = 1.0 - sum((w / total) ** 2 for w in weights.values())
    return participation


def per_channel_message_counts(
    channel_pks: list[int],
    start_date: datetime.date | None,
    end_date: datetime.date | None,
    *,
    alive: bool = True,
    extra_q: Q | None = None,
) -> dict[int, int]:
    """Return ``{channel_id: count}`` of messages in ``channel_pks`` honouring the
    date window and each channel's in-target attribution periods.

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
    # ~Q(channel=forwarded_from): re-forwarding one's own posts is not amplification
    # by others — the graph drops self-citation edges for the same reason.
    fwd_q = (
        Q(forwarded_from_id__in=channel_pks, channel_id__in=channel_pks)
        & ~Q(channel_id=F("forwarded_from_id"))
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
    """Populate in/out strength, fans, message count, and activity period on each node.

    ``in_deg``/``out_deg`` hold the weighted in/out **strength** — the sum of raw
    (un-rescaled) tie weights on a node's incoming/outgoing edges. They are summed
    over ``weight_raw`` rather than the ×10/max-normalised ``weight`` so the figure
    is portable across exports (the normalised ``weight`` depends on the single
    largest edge in the graph and is not comparable between runs).
    """
    measures_labels: list[tuple[str, str]] = [
        ("in_deg", "In-strength"),
        ("out_deg", "Out-strength"),
        ("fans", "Users"),
        ("messages_count", "Messages"),
    ]

    channel_pks = channel_pks_from_graph_data(graph_data, channel_dict)
    # Count only alive (non-lost) messages, so the displayed "Messages" column
    # reconciles with the Amplification / Content-originality denominators and the
    # network-wide content metrics — all of which run on Message.objects.alive().
    # (Previously alive=False, which inflated the column with un-fetchable lost-message
    # placeholders that the ratios never count, so the figures could not be derived
    # from one another.)
    message_counts = per_channel_message_counts(channel_pks, start_date, end_date, alive=True)
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
        # float(): networkx returns int 0 for a node with no edges on that side and
        # float otherwise; a mixed int/float column corrupts GEXF typing (declared
        # from the first node serialized) and duplicates GraphML keys.
        node["in_deg"] = float(graph.in_degree(node["id"], weight="weight_raw"))
        node["out_deg"] = float(graph.out_degree(node["id"], weight="weight_raw"))
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
