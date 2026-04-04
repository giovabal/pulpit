import datetime
import logging
from collections import defaultdict
from collections.abc import Callable
from typing import Any

from django.db.models import Count, Q, QuerySet

from network.utils import CommunityTableData, GraphData, make_date_q
from webapp.models import Message

import networkx as nx
import numpy as np

logger = logging.getLogger(__name__)

# Minimum community size for which avg_path_length / diameter are computed.
# Tiny communities (singletons, pairs) are trivially O(1) but incur WCC setup overhead;
# skipping them avoids calling weakly_connected_components on many 1–2 node subgraphs.
_PATH_LENGTH_MIN_NODES = 3


def _network_summary(graph: nx.DiGraph) -> dict[str, Any]:
    """Compute structural metrics for the whole graph."""
    n = graph.number_of_nodes()
    e = graph.number_of_edges()
    density = nx.density(graph)
    try:
        reciprocity = nx.overall_reciprocity(graph) if e > 0 else 0.0
    except Exception as exc:
        logger.debug("reciprocity unavailable: %s", exc)
        reciprocity = None
    try:
        avg_clustering = nx.average_clustering(graph)
    except Exception as exc:
        logger.debug("avg_clustering unavailable: %s", exc)
        avg_clustering = None
    avg_path_length = None
    diameter = None
    path_on_full = False
    wcc_count = None
    wcc_fraction = None
    scc_count = None
    scc_fraction = None
    if n >= 2:
        try:
            wccs = list(nx.weakly_connected_components(graph))
            largest_wcc = max(wccs, key=len)
            path_on_full = len(largest_wcc) == n
            wcc_count = len(wccs)
            wcc_fraction = len(largest_wcc) / n
            if len(largest_wcc) >= 2:
                ug = graph.subgraph(largest_wcc).to_undirected()
                avg_path_length = nx.average_shortest_path_length(ug)
                diameter = nx.diameter(ug)
        except Exception as exc:
            logger.debug("wcc/path_length/diameter unavailable: %s", exc)
        try:
            sccs = list(nx.strongly_connected_components(graph))
            largest_scc = max(sccs, key=len)
            scc_count = len(sccs)
            scc_fraction = len(largest_scc) / n
        except Exception as exc:
            logger.debug("scc unavailable: %s", exc)
    assortativity: dict[str, float | None] = {
        "in_in": None,
        "in_out": None,
        "out_in": None,
        "out_out": None,
    }
    if e >= 2:
        try:
            in_deg = dict(graph.in_degree())
            out_deg = dict(graph.out_degree())
            src_in = np.array([in_deg[u] for u, v in graph.edges()], dtype=float)
            src_out = np.array([out_deg[u] for u, v in graph.edges()], dtype=float)
            tgt_in = np.array([in_deg[v] for u, v in graph.edges()], dtype=float)
            tgt_out = np.array([out_deg[v] for u, v in graph.edges()], dtype=float)
            for key, x, y in [
                ("in_in", src_in, tgt_in),
                ("in_out", src_in, tgt_out),
                ("out_in", src_out, tgt_in),
                ("out_out", src_out, tgt_out),
            ]:
                if x.std() > 0 and y.std() > 0:
                    assortativity[key] = float(np.corrcoef(x, y)[0, 1])
        except Exception as exc:
            logger.debug("assortativity unavailable: %s", exc)
    return {
        "n": n,
        "e": e,
        "density": density,
        "reciprocity": reciprocity,
        "avg_clustering": avg_clustering,
        "avg_path_length": avg_path_length,
        "diameter": diameter,
        "path_on_full": path_on_full,
        "wcc_count": wcc_count,
        "wcc_fraction": wcc_fraction,
        "scc_count": scc_count,
        "scc_fraction": scc_fraction,
        "assortativity": assortativity,
    }


def _subgraph_metrics(nodes_set: set[str], graph: nx.DiGraph) -> dict[str, Any]:
    """Compute structural metrics for a community defined by nodes_set."""
    subgraph = graph.subgraph(nodes_set)
    n = subgraph.number_of_nodes()
    internal_edges = subgraph.number_of_edges()
    total_deg = sum(graph.in_degree(nd) + graph.out_degree(nd) for nd in nodes_set)
    external_edges = total_deg - 2 * internal_edges
    density = nx.density(subgraph)
    try:
        reciprocity = nx.overall_reciprocity(subgraph) if internal_edges > 0 else 0.0
    except Exception as exc:
        logger.debug("reciprocity unavailable for subgraph: %s", exc)
        reciprocity = None
    try:
        avg_clustering = nx.average_clustering(subgraph)
    except Exception as exc:
        logger.debug("avg_clustering unavailable for subgraph: %s", exc)
        avg_clustering = None
    avg_path_length = None
    diameter = None
    if n >= _PATH_LENGTH_MIN_NODES:
        try:
            wccs = list(nx.weakly_connected_components(subgraph))
            largest_wcc = max(wccs, key=len)
            if len(largest_wcc) >= 2:
                ug = subgraph.subgraph(largest_wcc).to_undirected()
                avg_path_length = nx.average_shortest_path_length(ug)
                diameter = nx.diameter(ug)
        except Exception as exc:
            logger.debug("wcc/path_length/diameter unavailable for subgraph: %s", exc)
    return {
        "internal_edges": internal_edges,
        "external_edges": external_edges,
        "density": density,
        "reciprocity": reciprocity,
        "avg_clustering": avg_clustering,
        "avg_path_length": avg_path_length,
        "diameter": diameter,
    }


def _freeman_centralization(values: list[float]) -> float | None:
    """Freeman (1978) graph centralization for a centrality measure.

    H = Σ_i (C_max - C_i) / [(n-1) · C_max]

    Returns None when the result is undefined (fewer than 2 nodes or C_max == 0).
    None entries in values are ignored.
    """
    clean = [v for v in values if v is not None]
    n = len(clean)
    if n < 2:
        return None
    c_max = max(clean)
    if c_max == 0:
        return None
    return sum(c_max - v for v in clean) / ((n - 1) * c_max)


def _network_content_metrics(
    channel_qs: QuerySet,
    start_date: datetime.date | None = None,
    end_date: datetime.date | None = None,
) -> dict[str, float | None]:
    """Compute network-wide content originality and amplification ratio from the DB."""
    channel_pks = list(channel_qs.values_list("pk", flat=True))
    msg_q = Q(channel_id__in=channel_pks) & make_date_q(start_date, end_date)
    agg = Message.objects.filter(msg_q).aggregate(
        total=Count("id"),
        forwarded_out=Count("id", filter=Q(forwarded_from__isnull=False)),
    )
    total = agg["total"]
    if total == 0:
        return {"network_originality": None, "network_amplification": None}
    forwarded_out = agg["forwarded_out"]
    fwd_in_q = Q(forwarded_from_id__in=channel_pks, channel_id__in=channel_pks) & make_date_q(start_date, end_date)
    forwards_received = Message.objects.filter(fwd_in_q).count()
    return {
        "network_originality": round(1 - forwarded_out / total, 4),
        "network_amplification": round(forwards_received / total, 4),
    }


def compute_community_metrics(
    graph_data: GraphData,
    communities_data: dict[str, Any],
    graph: nx.DiGraph,
    strategies: list[str],
    measures_labels: "list[tuple[str, str]] | None" = None,
    status_callback: "Callable[[str], None] | None" = None,
    channel_qs: "QuerySet | None" = None,
    start_date: datetime.date | None = None,
    end_date: datetime.date | None = None,
) -> CommunityTableData:
    """Pre-compute all structural metrics needed for community table outputs.

    ``measures_labels`` is the list of (node_key, display_label) pairs returned by the
    apply_* functions; when provided, Freeman centralization is computed for each measure.
    ``status_callback`` is called with a short label after each step completes
    so the caller can emit progress output between steps.
    ``channel_qs`` enables whole-network content originality and amplification ratio metrics.
    """
    network_summary = _network_summary(graph)
    centralizations: dict[str, tuple[float | None, str]] = {}
    if measures_labels:
        for key, label in measures_labels:
            values = [node[key] for node in graph_data["nodes"] if key in node]
            centralizations[key] = (_freeman_centralization(values), label)
    network_summary["centralizations"] = centralizations
    constraint_vals = [
        node["burt_constraint"] for node in graph_data["nodes"] if node.get("burt_constraint") is not None
    ]
    network_summary["mean_burt_constraint"] = sum(constraint_vals) / len(constraint_vals) if constraint_vals else None
    if channel_qs is not None:
        network_summary.update(_network_content_metrics(channel_qs, start_date, end_date))
    result: CommunityTableData = {"network_summary": network_summary, "strategies": {}}
    id_to_node: dict[str, dict] = {node["id"]: node for node in graph_data["nodes"]}
    if status_callback:
        status_callback("network")
    for strategy_key in strategies:
        strategy_data = communities_data.get(strategy_key)
        if not strategy_data:
            if status_callback:
                status_callback(strategy_key)
            continue
        label_to_nodes: dict[str, set[str]] = defaultdict(set)
        for node in graph_data["nodes"]:
            lbl = (node.get("communities") or {}).get(strategy_key)
            if lbl:
                label_to_nodes[lbl].add(node["id"])
        rows = []
        for group in strategy_data["groups"]:
            _community_id, _count, label, _hex_color = group
            nodes_set = label_to_nodes.get(str(label), set())
            metrics = (
                _subgraph_metrics(nodes_set, graph)
                if nodes_set
                else {
                    "internal_edges": 0,
                    "external_edges": 0,
                    "density": 0.0,
                    "reciprocity": 0.0,
                    "avg_clustering": None,
                    "avg_path_length": None,
                    "diameter": None,
                }
            )
            channels = sorted(
                (
                    {"label": id_to_node[nid].get("label") or nid, "url": id_to_node[nid].get("url") or ""}
                    for nid in nodes_set
                    if nid in id_to_node
                ),
                key=lambda c: c["label"].lower(),
            )
            rows.append({"group": group, "node_count": len(nodes_set), "metrics": metrics, "channels": channels})
        modularity = None
        if label_to_nodes:
            try:
                modularity = nx.community.modularity(graph, label_to_nodes.values())
            except Exception as exc:
                logger.debug("modularity unavailable for strategy %s: %s", strategy_key, exc)
        result["strategies"][strategy_key] = {"modularity": modularity, "rows": rows}
        if status_callback:
            status_callback(strategy_key)
    return result


def network_summary_rows(summary: dict[str, Any]) -> list[list[Any]]:
    """Return (label, value) rows for all whole-network metrics."""
    path_marker = " *" if not summary["path_on_full"] else ""
    rows: list[list[Any]] = [
        ["Nodes", summary["n"]],
        ["Edges", summary["e"]],
        ["Density", summary["density"]],
        ["Reciprocity", summary["reciprocity"]],
        ["Avg Clustering", summary["avg_clustering"]],
        [f"Avg Path Length{path_marker}", summary["avg_path_length"]],
        [f"Diameter{path_marker}", summary["diameter"]],
        ["WCC count", summary["wcc_count"]],
        ["Largest WCC fraction", summary["wcc_fraction"]],
        ["SCC count", summary["scc_count"]],
        ["Largest SCC fraction", summary["scc_fraction"]],
    ]
    for assort_key, assort_label in [
        ("in_in", "Assortativity in→in"),
        ("in_out", "Assortativity in→out"),
        ("out_in", "Assortativity out→in"),
        ("out_out", "Assortativity out→out"),
    ]:
        rows.append([assort_label, summary.get("assortativity", {}).get(assort_key)])
    if summary.get("mean_burt_constraint") is not None:
        rows.append(["Mean Burt's Constraint", summary["mean_burt_constraint"]])
    if summary.get("network_originality") is not None:
        rows.append(["Content Originality", summary["network_originality"]])
    if summary.get("network_amplification") is not None:
        rows.append(["Amplification Ratio", summary["network_amplification"]])
    for _key, (c_val, c_label) in summary.get("centralizations", {}).items():
        rows.append([f"{c_label} Centralization", c_val])
    return rows
