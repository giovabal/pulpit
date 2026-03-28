import datetime
import logging
import re
from math import isnan, log
from typing import Any

from django.db.models import Count, Max, Min, Q

from network.utils import GraphData, make_date_q
from webapp.models import Message

import networkx as nx

logger = logging.getLogger(__name__)


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

    channel_pks = [
        channel_dict[node["id"]]["channel"].pk for node in graph_data["nodes"] if channel_dict.get(node["id"])
    ]
    msg_q = Q(channel_id__in=channel_pks) & make_date_q(start_date, end_date)
    message_counts: dict[int, int] = {
        item["channel_id"]: item["total"]
        for item in Message.objects.filter(msg_q).values("channel_id").annotate(total=Count("id"))
    }
    activity_bounds: dict[int, dict] = {
        item["channel_id"]: {"min_date": item["min_date"], "max_date": item["max_date"]}
        for item in Message.objects.filter(channel_id__in=channel_pks, date__isnull=False)
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


def apply_pagerank(graph_data: GraphData, graph: nx.DiGraph) -> list[tuple[str, str]]:
    """Add PageRank score to each node."""
    key = "pagerank"
    pagerank_values: dict[str, float] = nx.pagerank(graph)
    for node in graph_data["nodes"]:
        if node["id"] in pagerank_values:
            node[key] = pagerank_values[node["id"]]
    return [(key, "PageRank")]


def apply_hits(graph_data: GraphData, graph: nx.DiGraph) -> list[tuple[str, str]]:
    """Add HITS hub and authority scores to each node."""
    try:
        hubs, authorities = nx.hits(graph)
    except nx.PowerIterationFailedConvergence:
        logger.warning("HITS failed to converge")
        return []
    for node in graph_data["nodes"]:
        node["hits_hub"] = hubs.get(node["id"], 0.0)
        node["hits_authority"] = authorities.get(node["id"], 0.0)
    return [("hits_hub", "HITS Hub"), ("hits_authority", "HITS Authority")]


def compute_betweenness(graph: nx.DiGraph) -> dict[str, float]:
    """Compute betweenness centrality and return the raw values dict."""
    return nx.betweenness_centrality(graph, weight="weight")


def apply_betweenness_centrality(
    graph_data: GraphData,
    graph: nx.DiGraph,
    betweenness: "dict[str, float] | None" = None,
) -> list[tuple[str, str]]:
    """Add betweenness centrality to each node.

    If ``betweenness`` is provided (pre-computed via ``compute_betweenness``),
    the nx call is skipped, allowing the caller to share one computation with
    ``apply_bridging_centrality``.
    """
    key = "betweenness"
    values = betweenness if betweenness is not None else compute_betweenness(graph)
    for node in graph_data["nodes"]:
        node[key] = values.get(node["id"], 0.0)
    return [(key, "Betweenness Centrality")]


def apply_in_degree_centrality(graph_data: GraphData, graph: nx.DiGraph) -> list[tuple[str, str]]:
    """Add normalized in-degree centrality to each node."""
    key = "in_degree_centrality"
    values: dict[str, float] = nx.in_degree_centrality(graph)
    for node in graph_data["nodes"]:
        node[key] = values.get(node["id"], 0.0)
    return [(key, "In-degree Centrality")]


def apply_out_degree_centrality(graph_data: GraphData, graph: nx.DiGraph) -> list[tuple[str, str]]:
    """Add normalized out-degree centrality to each node."""
    key = "out_degree_centrality"
    values: dict[str, float] = nx.out_degree_centrality(graph)
    for node in graph_data["nodes"]:
        node[key] = values.get(node["id"], 0.0)
    return [(key, "Out-degree Centrality")]


def apply_harmonic_centrality(graph_data: GraphData, graph: nx.DiGraph) -> list[tuple[str, str]]:
    """Add normalized harmonic centrality to each node."""
    key = "harmonic_centrality"
    n = graph.number_of_nodes()
    norm = (n - 1) if n > 1 else 1
    values: dict[str, float] = nx.harmonic_centrality(graph)
    for node in graph_data["nodes"]:
        node[key] = values.get(node["id"], 0.0) / norm
    return [(key, "Harmonic Centrality")]


def apply_katz_centrality(graph_data: GraphData, graph: nx.DiGraph) -> list[tuple[str, str]]:
    """Add Katz centrality to each node."""
    key = "katz_centrality"
    try:
        values: dict[str, float] = nx.katz_centrality(graph, weight="weight")
    except nx.PowerIterationFailedConvergence:
        logger.warning("Katz centrality failed to converge")
        return []
    for node in graph_data["nodes"]:
        node[key] = values.get(node["id"], 0.0)
    return [(key, "Katz Centrality")]


def apply_bridging_centrality(
    graph_data: GraphData,
    graph: nx.DiGraph,
    strategy_key: str,
    betweenness: "dict[str, float] | None" = None,
) -> list[tuple[str, str]]:
    """Add bridging centrality (betweenness × neighbor-community Shannon entropy) to each node.

    For each node, the Shannon entropy is computed over the community distribution of its
    neighbours weighted by edge strength. Nodes that connect many distinct communities score
    high on entropy; multiplying by betweenness surfaces nodes that are both structurally
    central and community-diverse.

    If ``betweenness`` is provided (pre-computed via ``compute_betweenness``), the nx call
    is skipped, allowing the caller to share one computation with ``apply_betweenness_centrality``.
    """
    key = "bridging_centrality"

    betweenness = betweenness if betweenness is not None else compute_betweenness(graph)

    community_map: dict[str, str] = {
        node_id: node_data["communities"][strategy_key]
        for node_id, node_data in graph.nodes(data="data")
        if node_data and strategy_key in (node_data.get("communities") or {})
    }

    for node in graph_data["nodes"]:
        node_id = node["id"]
        bt = betweenness.get(node_id, 0.0)

        community_weights: dict[str, float] = {}
        for pred in graph.predecessors(node_id):
            w = graph.edges[pred, node_id].get("weight", 1.0)
            c = community_map.get(pred)
            if c is not None:
                community_weights[c] = community_weights.get(c, 0.0) + w
        for succ in graph.successors(node_id):
            w = graph.edges[node_id, succ].get("weight", 1.0)
            c = community_map.get(succ)
            if c is not None:
                community_weights[c] = community_weights.get(c, 0.0) + w

        total = sum(community_weights.values())
        if total == 0.0 or len(community_weights) <= 1:
            entropy = 0.0
        else:
            entropy = -sum((w / total) * log(w / total) for w in community_weights.values())

        node[key] = bt * entropy

    return [(key, "Bridging Centrality")]


def apply_burt_constraint(graph_data: GraphData, graph: nx.DiGraph) -> list[tuple[str, str]]:
    """Add Burt's constraint to each node. Isolated nodes receive None (undefined)."""
    key = "burt_constraint"
    values: dict[str, float] = nx.constraint(graph)
    for node in graph_data["nodes"]:
        val = values.get(node["id"])
        node[key] = None if (val is None or isnan(val)) else round(val, 6)
    return [(key, "Burt's Constraint")]


def apply_amplification_factor(
    graph_data: GraphData,
    graph: nx.DiGraph,
    channel_dict: dict[str, Any],
    start_date: datetime.date | None = None,
    end_date: datetime.date | None = None,
) -> list[tuple[str, str]]:
    """Add amplification factor (forwards received / own message count) to each node."""
    key = "amplification_factor"

    channel_pks = [
        channel_dict[node["id"]]["channel"].pk for node in graph_data["nodes"] if channel_dict.get(node["id"])
    ]
    msg_q = Q(channel_id__in=channel_pks) & make_date_q(start_date, end_date)
    message_counts: dict[int, int] = {
        item["channel_id"]: item["total"]
        for item in Message.objects.filter(msg_q).values("channel_id").annotate(total=Count("id"))
    }

    fwd_q = Q(forwarded_from_id__in=channel_pks, channel_id__in=channel_pks) & make_date_q(start_date, end_date)
    forwards_received: dict[int, int] = {
        item["forwarded_from_id"]: item["total"]
        for item in Message.objects.filter(fwd_q).values("forwarded_from_id").annotate(total=Count("id"))
    }

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

    channel_pks = [
        channel_dict[node["id"]]["channel"].pk for node in graph_data["nodes"] if channel_dict.get(node["id"])
    ]
    msg_q = Q(channel_id__in=channel_pks) & make_date_q(start_date, end_date)
    message_counts: dict[int, int] = {
        item["channel_id"]: item["total"]
        for item in Message.objects.filter(msg_q).values("channel_id").annotate(total=Count("id"))
    }
    fwd_q = msg_q & Q(forwarded_from__isnull=False)
    forwarded_counts: dict[int, int] = {
        item["channel_id"]: item["total"]
        for item in Message.objects.filter(fwd_q).values("channel_id").annotate(total=Count("id"))
    }

    for node in graph_data["nodes"]:
        channel_entry = channel_dict.get(node["id"])
        if channel_entry is None:
            continue
        pk = channel_entry["channel"].pk
        mc = message_counts.get(pk, 0)
        node[key] = round(1 - forwarded_counts.get(pk, 0) / mc, 4) if mc > 0 else None

    return [(key, "Content Originality")]


# ─── Measure registry ──────────────────────────────────────────────────────────

VALID_MEASURES: frozenset[str] = frozenset(
    {
        "PAGERANK",
        "HITSHUB",
        "HITSAUTH",
        "BETWEENNESS",
        "INDEGCENTRALITY",
        "OUTDEGCENTRALITY",
        "HARMONICCENTRALITY",
        "KATZ",
        "BURTCONSTRAINT",
        "AMPLIFICATION",
        "CONTENTORIGINALITY",
    }
)

_BRIDGING_RE = re.compile(r"^BRIDGING(?:\(([A-Z]+)\))?$")
_BRIDGING_DEFAULT_STRATEGY = "LEIDEN"

# Expansion targets for the ALL shortcut
ALL_MEASURES: list[str] = [*sorted(VALID_MEASURES), "BRIDGING"]
ALL_STRATEGIES: list[str] = ["ORGANIZATION", "LEIDEN", "LOUVAIN", "KCORE", "INFOMAP", "WEAKCC", "STRONGCC"]

# Dispatch table: (settings key, progress label, apply function name)
# HITS and BRIDGING are handled separately because they have non-standard signatures.
MEASURE_STEPS: list[tuple[str, str, str]] = [
    ("PAGERANK", "pagerank", "apply_pagerank"),
    ("BETWEENNESS", "betweenness centrality", "apply_betweenness_centrality"),
    ("INDEGCENTRALITY", "in-degree centrality", "apply_in_degree_centrality"),
    ("OUTDEGCENTRALITY", "out-degree centrality", "apply_out_degree_centrality"),
    ("HARMONICCENTRALITY", "harmonic centrality", "apply_harmonic_centrality"),
    ("KATZ", "Katz centrality", "apply_katz_centrality"),
    ("BURTCONSTRAINT", "Burt's constraint", "apply_burt_constraint"),
]


def is_valid_measure(token: str) -> bool:
    return token in VALID_MEASURES or bool(_BRIDGING_RE.match(token))


def find_bridging_token(network_measures: list[str]) -> str | None:
    return next((m for m in network_measures if _BRIDGING_RE.match(m)), None)


def bridging_strategy(token: str) -> str:
    """Return the community strategy encoded in a BRIDGING token (defaults to LEIDEN)."""
    m = _BRIDGING_RE.match(token)
    return (m.group(1) or _BRIDGING_DEFAULT_STRATEGY) if m else _BRIDGING_DEFAULT_STRATEGY
