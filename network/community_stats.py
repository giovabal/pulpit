import datetime
import logging
from collections import defaultdict
from collections.abc import Callable
from typing import Any

from django.db.models import Count, Q, QuerySet

from network.utils import CommunityTableData, GraphData, channel_cutoff_q, make_date_q
from webapp.models import Message

import networkx as nx
import numpy as np

logger = logging.getLogger(__name__)

# Minimum community size for which avg_path_length / diameter are computed.
# Tiny communities (singletons, pairs) are trivially O(1) but incur WCC setup overhead;
# skipping them avoids calling weakly_connected_components on many 1–2 node subgraphs.
_PATH_LENGTH_MIN_NODES = 3


def _network_summary(graph: nx.DiGraph, selected_groups: "frozenset[str] | None" = None) -> dict[str, Any]:
    """Compute structural metrics for the whole graph.

    ``selected_groups`` controls which metric groups are computed.
    ``None`` means all groups (backward-compatible default).
    """

    def _sel(key: str) -> bool:
        return selected_groups is None or key in selected_groups

    n = graph.number_of_nodes()
    e = graph.number_of_edges()
    density = nx.density(graph)

    # ── PATHS — reciprocity, clustering, WCC/SCC path lengths ─────────────────
    reciprocity: float | None = None
    avg_clustering: float | None = None
    avg_path_length: float | None = None
    diameter: int | None = None
    path_on_full = True  # True = no footnote dagger when paths not computed
    wcc_count: int | None = None
    wcc_fraction: float | None = None
    scc_count: int | None = None
    scc_fraction: float | None = None
    avg_path_length_directed: float | None = None
    diameter_directed: int | None = None
    scc_path_on_full = True

    if _sel("PATHS"):
        try:
            reciprocity = nx.overall_reciprocity(graph) if e > 0 else 0.0
        except (nx.NetworkXError, nx.NetworkXAlgorithmError, ZeroDivisionError) as exc:
            logger.debug("reciprocity unavailable: %s", exc)
        try:
            avg_clustering = nx.average_clustering(graph)
        except (nx.NetworkXError, nx.NetworkXAlgorithmError, ZeroDivisionError) as exc:
            logger.debug("avg_clustering unavailable: %s", exc)

    need_wcc = _sel("PATHS") or _sel("COMPONENTS")
    need_scc = _sel("PATHS") or _sel("COMPONENTS")
    if n >= 2 and need_wcc:
        try:
            wccs = list(nx.weakly_connected_components(graph))
            largest_wcc = max(wccs, key=len)
            if _sel("COMPONENTS"):
                wcc_count = len(wccs)
                wcc_fraction = len(largest_wcc) / n
            if _sel("PATHS"):
                path_on_full = len(largest_wcc) == n
                if len(largest_wcc) >= 2:
                    ug = graph.subgraph(largest_wcc).to_undirected()
                    avg_path_length = nx.average_shortest_path_length(ug)
                    diameter = nx.diameter(ug)
        except (nx.NetworkXError, nx.NetworkXAlgorithmError, ZeroDivisionError) as exc:
            logger.debug("wcc/path_length/diameter unavailable: %s", exc)
    if n >= 2 and need_scc:
        try:
            sccs = list(nx.strongly_connected_components(graph))
            largest_scc = max(sccs, key=len)
            if _sel("COMPONENTS"):
                scc_count = len(sccs)
                scc_fraction = len(largest_scc) / n
            if _sel("PATHS"):
                scc_path_on_full = len(largest_scc) == n
                if len(largest_scc) >= 2:
                    scc_sub = graph.subgraph(largest_scc)
                    avg_path_length_directed = nx.average_shortest_path_length(scc_sub)
                    diameter_directed = nx.diameter(scc_sub)
        except (nx.NetworkXError, nx.NetworkXAlgorithmError, ZeroDivisionError) as exc:
            logger.debug("scc unavailable: %s", exc)

    # ── COHESION — transitivity, global efficiency, algebraic connectivity ─────
    # Transitivity — fraction of closed triads (O(m))
    # Global clustering coefficient (Watts & Strogatz 1998): closed triangles /
    # connected triples.  Complements avg_clustering (per-node average).
    transitivity: float | None = None
    # Global Efficiency — mean reciprocal path length (O(n*(n+m)))
    # Latora & Marchiori (2001): E = (1/n(n-1)) * Σ_{i≠j} 1/d(i,j).
    # Directed BFS, unreachable pairs contribute 0.
    global_efficiency: float | None = None
    # Algebraic Connectivity — Fiedler value (O(n²) approx.)
    # Fiedler (1973): second-smallest eigenvalue λ₂ of the Laplacian.
    # λ₂ = 0 for disconnected graphs; larger = stronger cohesion.
    algebraic_connectivity: float | None = None
    # Degree CV — coefficient of variation σ/μ (Pastor-Satorras & Vespignani 2001)
    in_degree_cv: float | None = None
    out_degree_cv: float | None = None
    if _sel("COHESION"):
        try:
            transitivity = round(nx.transitivity(graph), 6)
        except (nx.NetworkXError, nx.NetworkXAlgorithmError) as exc:
            logger.debug("transitivity unavailable: %s", exc)
        if n >= 2:
            try:
                total_inv_dist = 0.0
                for source in graph.nodes():
                    lengths = nx.single_source_shortest_path_length(graph, source)
                    total_inv_dist += sum(1.0 / d for target, d in lengths.items() if target != source)
                global_efficiency = round(total_inv_dist / (n * (n - 1)), 6)
            except (nx.NetworkXError, nx.NetworkXAlgorithmError, ZeroDivisionError) as exc:
                logger.debug("global_efficiency unavailable: %s", exc)
            try:
                ug_ac = graph.to_undirected()
                lcc_nodes = max(nx.connected_components(ug_ac), key=len)
                lcc_ac = ug_ac.subgraph(lcc_nodes)
                if len(lcc_ac) >= 2:
                    algebraic_connectivity = round(nx.algebraic_connectivity(lcc_ac, method="tracemin_pcg", seed=42), 6)
            except (nx.NetworkXError, nx.NetworkXAlgorithmError, ZeroDivisionError) as exc:
                logger.debug("algebraic_connectivity unavailable: %s", exc)
            in_arr = np.array([d for _, d in graph.in_degree()], dtype=float)
            out_arr = np.array([d for _, d in graph.out_degree()], dtype=float)
            in_mean = float(in_arr.mean())
            out_mean = float(out_arr.mean())
            if in_mean > 0:
                in_degree_cv = round(float(in_arr.std() / in_mean), 4)
            if out_mean > 0:
                out_degree_cv = round(float(out_arr.std() / out_mean), 4)

    # ── DEGCORRELATION — directed degree assortativity ─────────────────────────
    assortativity: dict[str, float | None] = {
        "in_in": None,
        "in_out": None,
        "out_in": None,
        "out_out": None,
    }
    if _sel("DEGCORRELATION") and e >= 2:
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
        except (ValueError, ZeroDivisionError, np.linalg.LinAlgError) as exc:
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
        "avg_path_length_directed": avg_path_length_directed,
        "diameter_directed": diameter_directed,
        "scc_path_on_full": scc_path_on_full,
        "transitivity": transitivity,
        "global_efficiency": global_efficiency,
        "algebraic_connectivity": algebraic_connectivity,
        "in_degree_cv": in_degree_cv,
        "out_degree_cv": out_degree_cv,
        "assortativity": assortativity,
        "_selected_groups": selected_groups,
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
    except (nx.NetworkXError, nx.NetworkXAlgorithmError, ZeroDivisionError) as exc:
        logger.debug("reciprocity unavailable for subgraph: %s", exc)
        reciprocity = None
    try:
        avg_clustering = nx.average_clustering(subgraph)
    except (nx.NetworkXError, nx.NetworkXAlgorithmError, ZeroDivisionError) as exc:
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
        except (nx.NetworkXError, nx.NetworkXAlgorithmError, ZeroDivisionError) as exc:
            logger.debug("wcc/path_length/diameter unavailable for subgraph: %s", exc)
    m = graph.number_of_edges()
    modularity_contribution = None
    if m > 0:
        d_out = sum(graph.out_degree(nd) for nd in nodes_set)
        d_in = sum(graph.in_degree(nd) for nd in nodes_set)
        modularity_contribution = round(internal_edges / m - (d_out * d_in) / (m * m), 6)
    # ── E-I Index — Krackhardt & Stern (1988) ────────────────────────────────
    # (external_ties − internal_ties) / (external_ties + internal_ties)
    # Range −1 (fully cohesive) to +1 (fully competitive/peripheral).
    ei_denom = external_edges + internal_edges
    ei_index = round((external_edges - internal_edges) / ei_denom, 4) if ei_denom > 0 else None

    return {
        "internal_edges": internal_edges,
        "external_edges": external_edges,
        "ei_index": ei_index,
        "density": density,
        "reciprocity": reciprocity,
        "avg_clustering": avg_clustering,
        "avg_path_length": avg_path_length,
        "diameter": diameter,
        "modularity_contribution": modularity_contribution,
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


def _count_channel_types(channel_qs: QuerySet) -> dict[str, int]:
    """Count channels per entity type (CHANNEL, GROUP, USER)."""
    return {
        "CHANNEL": channel_qs.filter(is_user_account=False, megagroup=False, gigagroup=False).count(),
        "GROUP": channel_qs.filter(Q(megagroup=True) | Q(gigagroup=True), is_user_account=False).count(),
        "USER": channel_qs.filter(is_user_account=True).count(),
    }


def _network_content_metrics(
    channel_qs: QuerySet,
    start_date: datetime.date | None = None,
    end_date: datetime.date | None = None,
) -> dict[str, float | None]:
    """Compute network-wide content originality and amplification ratio from the DB."""
    channel_pks = list(channel_qs.values_list("pk", flat=True))
    msg_q = Q(channel_id__in=channel_pks) & make_date_q(start_date, end_date) & channel_cutoff_q()
    agg = Message.objects.filter(msg_q).aggregate(
        total=Count("id"),
        forwarded_out=Count("id", filter=Q(forwarded_from__isnull=False)),
    )
    total = agg["total"]
    if total == 0:
        return {"network_originality": None, "network_amplification": None}
    forwarded_out = agg["forwarded_out"]
    fwd_in_q = (
        Q(forwarded_from_id__in=channel_pks, channel_id__in=channel_pks)
        & make_date_q(start_date, end_date)
        & channel_cutoff_q()
    )
    forwards_received = Message.objects.filter(fwd_in_q).count()
    return {
        "network_originality": round(1 - forwarded_out / total, 4),
        "network_amplification": round(forwards_received / total, 4),
    }


def _compute_org_cross_tab(
    nodes: list[dict],
    strategy_rows: list[dict],
    strategy_key: str,
    pk_to_org: "dict[str, str]",
) -> "dict | None":
    """Cross-tabulation of organisations vs. community groups.

    Returns None when fewer than two organisations are present in the graph.
    The returned dict has:
      ``orgs``           — sorted list of organisation names (row labels)
      ``communities``    — community labels in strategy_rows order (column labels)
      ``comm_colors``    — hex colour per community column
      ``pct_by_org``     — matrix[org_idx][comm_idx]: % of that org's nodes in the community
      ``pct_by_community``— matrix[org_idx][comm_idx]: % of that community's nodes from the org
    """
    # Each row has a "group" tuple of (id, count, label, hex_color).
    community_labels = [row["group"][2] for row in strategy_rows]
    if not community_labels:
        return None
    counts: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    org_names_seen: set[str] = set()
    for node in nodes:
        org_name = pk_to_org.get(node["id"])
        if org_name is None:
            continue
        comm_label = (node.get("communities") or {}).get(strategy_key)
        if comm_label is None:
            continue
        counts[org_name][comm_label] += 1
        org_names_seen.add(org_name)
    if len(org_names_seen) < 2:
        return None
    orgs = sorted(org_names_seen)
    org_totals = {org: sum(counts[org][c] for c in community_labels) for org in orgs}
    comm_totals = {c: sum(counts[org][c] for org in orgs) for c in community_labels}
    comm_colors = {row["group"][2]: row["group"][3] for row in strategy_rows}
    pct_by_org: list[list[float | None]] = []
    pct_by_community: list[list[float | None]] = []
    for org in orgs:
        row_by_org: list[float | None] = []
        row_by_comm: list[float | None] = []
        for comm in community_labels:
            cnt = counts[org][comm]
            row_by_org.append(round(cnt / org_totals[org] * 100, 1) if org_totals[org] else None)
            row_by_comm.append(round(cnt / comm_totals[comm] * 100, 1) if comm_totals[comm] else None)
        pct_by_org.append(row_by_org)
        pct_by_community.append(row_by_comm)
    return {
        "orgs": orgs,
        "communities": community_labels,
        "comm_colors": [comm_colors.get(c, "#cccccc") for c in community_labels],
        "pct_by_org": pct_by_org,
        "pct_by_community": pct_by_community,
    }


def _compute_strategy_entry(
    strategy_key: str,
    strategy_data: dict[str, Any],
    graph_data: GraphData,
    graph: nx.DiGraph,
    id_to_node: dict[str, dict],
    pk_to_org: dict[str, str],
) -> dict[str, Any]:
    """Compute metrics for a single community-detection strategy."""
    label_to_nodes: dict[str, set[str]] = defaultdict(set)
    for node in graph_data["nodes"]:
        lbl = (node.get("communities") or {}).get(strategy_key)
        if lbl is not None:
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
                "ei_index": None,
                "density": 0.0,
                "reciprocity": 0.0,
                "avg_clustering": None,
                "avg_path_length": None,
                "diameter": None,
                "modularity_contribution": None,
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
        except (nx.NetworkXError, nx.NetworkXAlgorithmError, ZeroDivisionError, ValueError) as exc:
            logger.debug("modularity unavailable for strategy %s: %s", strategy_key, exc)

    # ── Inter-community edge ratio ────────────────────────────────────────────
    # Fraction of all directed edges whose source and target belong to different
    # communities (or are unassigned).  High = fragmented; low = cohesive.
    total_edges = graph.number_of_edges()
    inter_community_edge_ratio: float | None = None
    if total_edges > 0 and label_to_nodes:
        node_to_community: dict[str, str] = {}
        for lbl, nodes in label_to_nodes.items():
            for nd in nodes:
                node_to_community[nd] = str(lbl)
        cross = sum(1 for u, v in graph.edges() if node_to_community.get(u) != node_to_community.get(v))
        inter_community_edge_ratio = round(cross / total_edges, 4)

    # ── Mean E-I index (weighted by community connection volume) ─────────────
    mean_ei_index: float | None = None
    ei_weights = [
        (row["metrics"]["ei_index"], row["metrics"]["internal_edges"] + row["metrics"]["external_edges"])
        for row in rows
        if row["metrics"].get("ei_index") is not None
    ]
    if ei_weights:
        total_w = sum(w for _, w in ei_weights)
        if total_w > 0:
            mean_ei_index = round(sum(ei * w for ei, w in ei_weights) / total_w, 4)

    entry: dict[str, Any] = {
        "modularity": modularity,
        "inter_community_edge_ratio": inter_community_edge_ratio,
        "mean_ei_index": mean_ei_index,
        "rows": rows,
    }
    if pk_to_org:
        cross_tab = _compute_org_cross_tab(graph_data["nodes"], rows, strategy_key, pk_to_org)
        if cross_tab is not None:
            entry["org_cross_tab"] = cross_tab
    return entry


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
    selected_network_groups: "frozenset[str] | None" = None,
) -> CommunityTableData:
    """Pre-compute all structural metrics needed for community table outputs.

    ``measures_labels`` is the list of (node_key, display_label) pairs returned by the
    apply_* functions; when provided, Freeman centralization is computed for each measure.
    ``status_callback`` is called with a short label after each step completes
    so the caller can emit progress output between steps.
    ``channel_qs`` enables whole-network content originality and amplification ratio metrics.
    ``selected_network_groups`` restricts which whole-network stat groups are computed;
    ``None`` means all groups (backward-compatible default).
    """

    def _grp(key: str) -> bool:
        return selected_network_groups is None or key in selected_network_groups

    network_summary = _network_summary(graph, selected_network_groups)

    centralizations: dict[str, tuple[float | None, str]] = {}
    if _grp("CENTRALIZATION") and measures_labels:
        for key, label in measures_labels:
            values = [node[key] for node in graph_data["nodes"] if key in node]
            centralizations[key] = (_freeman_centralization(values), label)
    network_summary["centralizations"] = centralizations

    if _grp("CENTRALIZATION"):
        constraint_vals = [
            node["burt_constraint"] for node in graph_data["nodes"] if node.get("burt_constraint") is not None
        ]
        network_summary["mean_burt_constraint"] = (
            sum(constraint_vals) / len(constraint_vals) if constraint_vals else None
        )
    else:
        network_summary["mean_burt_constraint"] = None

    pk_to_org: dict[str, str] = {}
    if channel_qs is not None:
        if _grp("CONTENT"):
            network_summary.update(_network_content_metrics(channel_qs, start_date, end_date))
        type_counts = _count_channel_types(channel_qs)
        types_present = {k: v for k, v in type_counts.items() if v > 0}
        if len(types_present) > 1:
            network_summary["channel_type_counts"] = types_present
        pk_to_org = {
            str(pk): name for pk, name in channel_qs.values_list("pk", "organization__name") if name is not None
        }
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
        result["strategies"][strategy_key] = _compute_strategy_entry(
            strategy_key, strategy_data, graph_data, graph, id_to_node, pk_to_org
        )
        if status_callback:
            status_callback(strategy_key)
    return result


_CHANNEL_TYPE_LABELS: dict[str, str] = {
    "CHANNEL": "Broadcast channels",
    "GROUP": "Groups",
    "USER": "User accounts",
}

# Maps display group labels (used in row tuples) to network stat group keys.
_DISPLAY_GROUP_TO_KEY: dict[str, str] = {
    "Size": "SIZE",
    "Transitivity & paths": "PATHS",
    "Cohesion": "COHESION",
    "Component structure": "COMPONENTS",
    "Degree correlation": "DEGCORRELATION",
    "Centralization": "CENTRALIZATION",
    "Content": "CONTENT",
}


def network_summary_rows(summary: dict[str, Any]) -> list[tuple[str, Any, str]]:
    """Return (label, value, group) rows for whole-network metrics.

    Rows belonging to groups absent from ``summary["_selected_groups"]`` are
    omitted.  When ``_selected_groups`` is absent or ``None`` all rows are returned.
    """
    sel: "frozenset[str] | None" = summary.get("_selected_groups")

    def _include(display_group: str) -> bool:
        if sel is None:
            return True
        return _DISPLAY_GROUP_TO_KEY.get(display_group) in sel

    path_marker = " †" if not summary["path_on_full"] else ""
    scc_has_directed = summary.get("avg_path_length_directed") is not None
    scc_path_marker = " ‡" if (scc_has_directed and not summary.get("scc_path_on_full", True)) else ""
    rows: list[tuple[str, Any, str]] = []
    if _include("Size"):
        rows.append(("Nodes", summary["n"], "Size"))
        for type_name, count in summary.get("channel_type_counts", {}).items():
            rows.append((_CHANNEL_TYPE_LABELS.get(type_name, type_name), count, "Size"))
        rows += [
            ("Edges", summary["e"], "Size"),
            ("Edges / Nodes", round(summary["e"] / summary["n"], 4) if summary["n"] else None, "Size"),
            ("Density (0–1)", summary["density"], "Size"),
        ]
    if _include("Transitivity & paths"):
        rows += [
            ("Reciprocity (0–1)", summary["reciprocity"], "Transitivity & paths"),
            ("Avg Clustering (0–1)", summary["avg_clustering"], "Transitivity & paths"),
            (f"Avg Path Length{path_marker}", summary["avg_path_length"], "Transitivity & paths"),
            (f"Diameter{path_marker}", summary["diameter"], "Transitivity & paths"),
            (
                f"Directed Avg Path Length{scc_path_marker}",
                summary.get("avg_path_length_directed"),
                "Transitivity & paths",
            ),
            (f"Directed Diameter{scc_path_marker}", summary.get("diameter_directed"), "Transitivity & paths"),
        ]
    if _include("Cohesion"):
        rows += [
            ("Transitivity (0–1)", summary.get("transitivity"), "Cohesion"),
            ("Global Efficiency (0–1)", summary.get("global_efficiency"), "Cohesion"),
            (f"Algebraic Connectivity{path_marker}", summary.get("algebraic_connectivity"), "Cohesion"),
            ("In-degree CV", summary.get("in_degree_cv"), "Cohesion"),
            ("Out-degree CV", summary.get("out_degree_cv"), "Cohesion"),
        ]
    if _include("Component structure"):
        rows += [
            ("WCC count", summary["wcc_count"], "Component structure"),
            ("Largest WCC fraction (0–1)", summary["wcc_fraction"], "Component structure"),
            ("SCC count", summary["scc_count"], "Component structure"),
            ("Largest SCC fraction (0–1)", summary["scc_fraction"], "Component structure"),
        ]
    if _include("Degree correlation"):
        for assort_key, assort_label in [
            ("in_in", "Assortativity in→in (−1–1)"),
            ("in_out", "Assortativity in→out (−1–1)"),
            ("out_in", "Assortativity out→in (−1–1)"),
            ("out_out", "Assortativity out→out (−1–1)"),
        ]:
            rows.append((assort_label, summary.get("assortativity", {}).get(assort_key), "Degree correlation"))
    if _include("Centralization"):
        if summary.get("mean_burt_constraint") is not None:
            rows.append(("Mean Burt's Constraint (0–1)", summary["mean_burt_constraint"], "Centralization"))
        for _key, (c_val, c_label) in summary.get("centralizations", {}).items():
            rows.append((f"{c_label} Centralization (0–1)", c_val, "Centralization"))
    if _include("Content"):
        if summary.get("network_originality") is not None:
            rows.append(("Content Originality (0–1)", summary["network_originality"], "Content"))
        if summary.get("network_amplification") is not None:
            rows.append(("Amplification Ratio", summary["network_amplification"], "Content"))
    return rows
