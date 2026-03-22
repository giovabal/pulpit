import datetime
import html as _html
import json
import logging
import os
import re
import shutil
from collections import defaultdict
from collections.abc import Callable
from math import log, sqrt
from typing import Any

from django.conf import settings
from django.db.models import Count, Max, Min, Q, QuerySet
from django.template.loader import render_to_string

from webapp.models import Channel, Message

import networkx as nx
import numpy as np
import openpyxl
from openpyxl.styles import Font, PatternFill

logger = logging.getLogger(__name__)

_ISOLATED_GRID_DIVISIONS: int = 200

type GraphData = dict[str, list[dict[str, Any]]]


def build_graph_data(
    graph: nx.DiGraph,
    channel_dict: dict[str, Any],
    positions: dict[str, tuple[float, float]],
) -> GraphData:
    """Serialize graph nodes and edges into the output dict."""
    graph_data: GraphData = {"nodes": [], "edges": []}

    for node_id, node_data in graph.nodes(data=True):
        pos = positions.get(node_data["data"]["pk"])
        node_info: dict[str, Any] = {
            "id": node_id,
            "x": float(pos[0]) if pos is not None else 0.0,
            "y": float(pos[1]) if pos is not None else 0.0,
        }
        for key in (
            "label",
            "communities",
            "color",
            "pic",
            "url",
            "activity_period",
            "fans",
            "in_deg",
            "is_lost",
            "messages_count",
            "out_deg",
        ):
            node_info[key] = node_data["data"][key]
        graph_data["nodes"].append(node_info)

    for index, (source, target, edge_data) in enumerate(graph.edges(data=True)):
        graph_data["edges"].append(
            {
                "source": source,
                "target": target,
                "weight": edge_data.get("weight", 0),
                "color": edge_data.get("color", ""),
                "id": index,
            }
        )

    return graph_data


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
    msg_q = Q(channel_id__in=channel_pks)
    if start_date:
        msg_q &= Q(date__date__gte=start_date)
    if end_date:
        msg_q &= Q(date__date__lte=end_date)
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


def apply_betweenness_centrality(graph_data: GraphData, graph: nx.DiGraph) -> list[tuple[str, str]]:
    """Add betweenness centrality to each node."""
    key = "betweenness"
    values: dict[str, float] = nx.betweenness_centrality(graph, weight="weight")
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


def apply_bridging_centrality(graph_data: GraphData, graph: nx.DiGraph, strategy_key: str) -> list[tuple[str, str]]:
    """Add bridging centrality (betweenness × neighbor-community Shannon entropy) to each node.

    For each node, the Shannon entropy is computed over the community distribution of its
    neighbours weighted by edge strength. Nodes that connect many distinct communities score
    high on entropy; multiplying by betweenness surfaces nodes that are both structurally
    central and community-diverse.
    """
    key = "bridging_centrality"

    betweenness: dict[str, float] = nx.betweenness_centrality(graph, weight="weight")

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


def find_main_component(graph: nx.DiGraph) -> set[str]:
    return max(nx.weakly_connected_components(graph), key=len)


def reposition_isolated_nodes(graph_data: GraphData, main_component: set[str]) -> None:
    """Move isolated nodes (outside the main component) into a grid near the main cluster."""
    main_nodes = [node for node in graph_data["nodes"] if node["id"] in main_component]
    isolated_nodes = [index for index, node in enumerate(graph_data["nodes"]) if node["id"] not in main_component]
    if not main_nodes:
        return
    max_x = max(node["x"] for node in main_nodes)
    min_x = min(node["x"] for node in main_nodes)
    max_y = max(node["y"] for node in main_nodes)
    d = abs(max_x - min_x) / _ISOLATED_GRID_DIVISIONS if max_x != min_x else 1.0
    col = int(sqrt(len(isolated_nodes))) + 1
    for i in range(col):
        for j in range(col):
            idx = i * col + j
            if len(isolated_nodes) > idx:
                graph_data["nodes"][isolated_nodes[idx]]["x"] = max_x - i * d
                graph_data["nodes"][isolated_nodes[idx]]["y"] = max_y - j * d


def ensure_graph_root(root_target: str) -> None:
    if os.path.isdir(root_target):
        for entry in os.scandir(root_target):
            if entry.is_dir(follow_symlinks=False):
                shutil.rmtree(entry.path)
            else:
                os.remove(entry.path)
    else:
        os.makedirs(root_target)
    try:
        shutil.copytree("webapp_engine/map", root_target, dirs_exist_ok=True)
    except OSError as e:
        logger.warning("Could not copy map template to %s: %s", root_target, e)


def apply_robots_to_graph_html(root_target: str, seo: bool, project_title: str = "") -> None:
    """Patch the robots meta tag and title in the static index.html after it is copied."""
    index_path = os.path.join(root_target, "index.html")
    if not os.path.exists(index_path):
        return
    with open(index_path) as f:
        content = f.read()
    if seo:
        content = content.replace(
            '  <meta name="robots" content="noindex">',
            '  <meta name="robots" content="index, follow">',
        )
    if project_title:
        escaped = _html.escape(project_title)
        content = re.sub(r"<title>[^<]*</title>", f"<title>{escaped}</title>", content)
        content = re.sub(
            r'(<h4 class="modal-title" id="about_modalLabel">)[^<]*(</h4>)',
            rf"\g<1>{escaped}\g<2>",
            content,
        )
    with open(index_path, "w") as f:
        f.write(content)


def write_robots_txt(root_target: str, seo: bool) -> None:
    """Write a robots.txt that either allows or disallows all crawlers."""
    if seo:
        content = "User-agent: *\nAllow: /\n"
    else:
        content = "User-agent: *\nDisallow: /\n"
    with open(os.path.join(root_target, "robots.txt"), "w") as f:
        f.write(content)


def write_graph_files(
    graph_data: GraphData,
    communities_data: dict[str, Any],
    measures_labels: list[tuple[str, str]],
    channel_qs: "QuerySet[Channel]",
    output_filename: str,
    accessory_filename: str,
) -> None:
    with open(output_filename, "w") as outputfile:
        outputfile.write(json.dumps(graph_data))

    accessory_payload: dict[str, Any] = {
        "communities": communities_data,
        "measures": measures_labels,
        "total_pages_count": channel_qs.count(),
    }
    with open(accessory_filename, "w") as accessoryfile:
        accessoryfile.write(json.dumps(accessory_payload))


def copy_channel_media(channel_qs: QuerySet[Channel], root_target: str) -> None:
    for username, telegram_id in channel_qs.values_list("username", "telegram_id"):
        channel_dir = username or str(telegram_id)
        src = os.path.join(settings.MEDIA_ROOT, "channels", channel_dir, "profile")
        dst = os.path.join(root_target, "channels", channel_dir, "profile")
        try:
            shutil.copytree(src, dst)
        except FileNotFoundError:
            pass
        except OSError as e:
            logger.warning("Could not copy media for channel %s: %s", channel_dir, e)


_BASE_MEASURE_KEYS: frozenset[str] = frozenset({"in_deg", "out_deg", "fans", "messages_count"})


def _heatmap_bg(val: float | int | None, col_min: float, col_max: float) -> str:
    """Subtle blue heatmap cell background: white (min) → #dceaf9 (max)."""
    if val is None or col_min >= col_max:
        return ""
    ratio = (val - col_min) / (col_max - col_min)
    r = round(255 - ratio * 35)
    g = round(255 - ratio * 21)
    b = round(255 - ratio * 6)
    return f"background-color:rgb({r},{g},{b})"


def _num_cell_dict(val: Any, key: str, hm_ranges: dict[str, tuple[float, float]]) -> dict:
    bg = _heatmap_bg(val, *hm_ranges[key]) if key in hm_ranges else ""
    return {
        "display": str(val) if val is not None else "",
        "css_class": "number",
        "sort_value": str(val) if val is not None else "",
        "style": bg,
        "link": "",
    }


def _float_cell_dict(val: Any, key: str, hm_ranges: dict[str, tuple[float, float]]) -> dict:
    bg = _heatmap_bg(val, *hm_ranges[key]) if key in hm_ranges else ""
    return {
        "display": f"{val:.4f}" if val is not None else "",
        "css_class": "number",
        "sort_value": str(val) if val is not None else "",
        "style": bg,
        "link": "",
    }


def write_table_html(
    graph_data: GraphData,
    measures_labels: list[tuple[str, str]],
    strategies: list[str],
    output_filename: str,
    seo: bool = False,
    project_title: str = "",
) -> None:
    extra = [(k, lbl) for k, lbl in measures_labels if k not in _BASE_MEASURE_KEYS]
    pagerank_col = next(((k, lbl) for k, lbl in extra if k == "pagerank"), None)
    other_extra = [(k, lbl) for k, lbl in extra if k != "pagerank"]
    nodes = sorted(graph_data["nodes"], key=lambda n: n.get("in_deg") or 0, reverse=True)

    headers = [
        {"label": "Channel", "css_class": ""},
        {"label": "Users", "css_class": "number"},
        {"label": "Messages", "css_class": "number"},
        {"label": "Inbound", "css_class": "number"},
        {"label": "Outbound", "css_class": "number"},
    ]
    if pagerank_col:
        headers.append({"label": pagerank_col[1], "css_class": "number"})
    headers += [{"label": lbl, "css_class": "number"} for _, lbl in other_extra]
    headers += [{"label": s.capitalize(), "css_class": ""} for s in strategies]
    headers += [{"label": "Activity start", "css_class": ""}, {"label": "Activity end", "css_class": ""}]

    _hm_int_keys = ["fans", "messages_count", "in_deg", "out_deg"]
    _hm_float_keys = ([pagerank_col[0]] if pagerank_col else []) + [k for k, _ in other_extra]
    hm_ranges: dict[str, tuple[float, float]] = {}
    for _k in _hm_int_keys + _hm_float_keys:
        _vals = [v for node in nodes if (v := node.get(_k)) is not None]
        if _vals:
            hm_ranges[_k] = (min(_vals), max(_vals))

    rows = []
    for node in nodes:
        label = node.get("label") or node["id"]
        url = node.get("url") or ""
        row: list[dict] = [{"display": label, "css_class": "", "sort_value": "", "style": "", "link": url}]
        for key in ("fans", "messages_count", "in_deg", "out_deg"):
            row.append(_num_cell_dict(node.get(key), key, hm_ranges))
        if pagerank_col:
            row.append(_float_cell_dict(node.get(pagerank_col[0]), pagerank_col[0], hm_ranges))
        for key, _ in other_extra:
            row.append(_float_cell_dict(node.get(key), key, hm_ranges))
        communities = node.get("communities") or {}
        for s in strategies:
            row.append(
                {"display": str(communities.get(s, "")), "css_class": "", "sort_value": "", "style": "", "link": ""}
            )
        row.append(
            {"display": node.get("activity_start") or "", "css_class": "", "sort_value": "", "style": "", "link": ""}
        )
        row.append(
            {"display": node.get("activity_end") or "", "css_class": "", "sort_value": "", "style": "", "link": ""}
        )
        rows.append(row)

    n = len(nodes)
    if seo:
        title = f"{project_title} | Channels" if project_title else "Channel network data"
        robots_meta = "index, follow"
    else:
        title = f"{project_title} | Channels" if project_title else "Channels"
        robots_meta = "noindex, nofollow"

    context = {
        "title": title,
        "robots_meta": robots_meta,
        "description": (
            f"Network data for {n} Telegram channels, "
            "including activity metrics, inbound and outbound connections, and community assignments."
        ),
        "n_channels": n,
        "headers": headers,
        "rows": rows,
    }
    content = render_to_string("network/channel_table.html", context)
    with open(output_filename, "w") as f:
        f.write(content)


def write_table_xlsx(
    graph_data: GraphData,
    measures_labels: list[tuple[str, str]],
    strategies: list[str],
    output_filename: str,
    project_title: str = "",
) -> None:
    extra = [(k, lbl) for k, lbl in measures_labels if k not in _BASE_MEASURE_KEYS]
    pagerank_col = next(((k, lbl) for k, lbl in extra if k == "pagerank"), None)
    other_extra = [(k, lbl) for k, lbl in extra if k != "pagerank"]
    nodes = sorted(graph_data["nodes"], key=lambda n: n.get("in_deg") or 0, reverse=True)

    wb = openpyxl.Workbook()
    if project_title:
        wb.properties.title = project_title
    ws = wb.active
    ws.title = "Channels"

    headers = ["Channel", "URL", "Users", "Messages", "Inbound", "Outbound"]
    if pagerank_col:
        headers.append(pagerank_col[1])
    headers += [lbl for _, lbl in other_extra]
    headers += [s.capitalize() for s in strategies]
    headers += ["Activity start", "Activity end"]
    ws.append(headers)
    for cell in ws[1]:
        cell.font = Font(bold=True)

    for node in nodes:
        communities = node.get("communities") or {}
        row: list[Any] = [
            node.get("label") or node["id"],
            node.get("url") or "",
            node.get("fans"),
            node.get("messages_count"),
            node.get("in_deg"),
            node.get("out_deg"),
        ]
        if pagerank_col:
            row.append(node.get(pagerank_col[0]))
        for key, _ in other_extra:
            row.append(node.get(key))
        for s in strategies:
            row.append(communities.get(s, ""))
        row.append(node.get("activity_start") or "")
        row.append(node.get("activity_end") or "")
        ws.append(row)

    wb.save(output_filename)


def _network_summary(graph: nx.DiGraph) -> dict[str, Any]:
    """Compute structural metrics for the whole graph."""
    n = graph.number_of_nodes()
    e = graph.number_of_edges()
    density = nx.density(graph)
    try:
        reciprocity = nx.overall_reciprocity(graph) if e > 0 else 0.0
    except Exception:
        reciprocity = None
    try:
        avg_clustering = nx.average_clustering(graph)
    except Exception:
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
        except Exception:
            pass
        try:
            sccs = list(nx.strongly_connected_components(graph))
            largest_scc = max(sccs, key=len)
            scc_count = len(sccs)
            scc_fraction = len(largest_scc) / n
        except Exception:
            pass
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
        except Exception:
            pass
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
    except Exception:
        reciprocity = None
    try:
        avg_clustering = nx.average_clustering(subgraph)
    except Exception:
        avg_clustering = None
    avg_path_length = None
    diameter = None
    if n >= 2:
        try:
            wccs = list(nx.weakly_connected_components(subgraph))
            largest_wcc = max(wccs, key=len)
            if len(largest_wcc) >= 2:
                ug = subgraph.subgraph(largest_wcc).to_undirected()
                avg_path_length = nx.average_shortest_path_length(ug)
                diameter = nx.diameter(ug)
        except Exception:
            pass
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


type CommunityTableData = dict[str, Any]
# Structure:
# {
#   "network_summary": dict,          # from _network_summary() plus "centralizations"
#   "strategies": {
#     strategy_key: [                 # ordered as in communities_data
#       {"group": tuple, "node_count": int, "metrics": dict},
#       ...
#     ]
#   }
# }


def compute_community_metrics(
    graph_data: GraphData,
    communities_data: dict[str, Any],
    graph: nx.DiGraph,
    strategies: list[str],
    measures_labels: "list[tuple[str, str]] | None" = None,
    status_callback: "Callable[[str], None] | None" = None,
) -> CommunityTableData:
    """Pre-compute all structural metrics needed for community table outputs.

    ``measures_labels`` is the list of (node_key, display_label) pairs returned by the
    apply_* functions; when provided, Freeman centralization is computed for each measure.
    ``status_callback`` is called with a short label after each step completes
    so the caller can emit progress output between steps.
    """
    network_summary = _network_summary(graph)
    centralizations: dict[str, tuple[float | None, str]] = {}
    if measures_labels:
        for key, label in measures_labels:
            values = [node[key] for node in graph_data["nodes"] if key in node]
            centralizations[key] = (_freeman_centralization(values), label)
    network_summary["centralizations"] = centralizations
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
            except Exception:
                pass
        result["strategies"][strategy_key] = {"modularity": modularity, "rows": rows}
        if status_callback:
            status_callback(strategy_key)
    return result


def _network_summary_rows(summary: dict[str, Any]) -> list[list[Any]]:
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
    for _key, (c_val, c_label) in summary.get("centralizations", {}).items():
        rows.append([f"{c_label} Centralization", c_val])
    return rows


def _build_scatter(
    graph_data: "GraphData",
    x_key: str,
    y_key: str,
    x_label: str,
    y_label: str,
) -> "tuple[str, str] | None":
    """Build a Bokeh scatter plot for any two node measures.

    Returns (bokeh_script, bokeh_div), or None if the measures are absent.
    INLINE resources are rendered separately (shared across plots).
    """
    try:
        from bokeh.embed import components
        from bokeh.models import ColumnDataSource, HoverTool
        from bokeh.plotting import figure
    except ImportError:
        return None

    nodes_with_data = [n for n in graph_data["nodes"] if n.get(x_key) is not None and n.get(y_key) is not None]
    if not nodes_with_data:
        return None

    xs = [n[x_key] for n in nodes_with_data]
    ys = [n[y_key] for n in nodes_with_data]
    labels = [n.get("label") or n["id"] for n in nodes_with_data]
    fans = [n.get("fans") or 0 for n in nodes_with_data]
    msgs = [n.get("messages_count") or 0 for n in nodes_with_data]

    source = ColumnDataSource({"x": xs, "y": ys, "label": labels, "fans": fans, "msgs": msgs})

    p = figure(
        width=1000,
        height=700,
        x_axis_type="log",
        y_axis_type="log",
        tools="pan,wheel_zoom,box_zoom,reset,save",
        x_axis_label=x_label,
        y_axis_label=y_label,
        toolbar_location="above",
    )
    p.toolbar.logo = None
    p.background_fill_color = "#fafafa"
    p.grid.grid_line_color = "#e5e7eb"
    p.axis.axis_line_color = "#9ca3af"
    p.axis.major_tick_line_color = "#9ca3af"
    p.axis.minor_tick_line_color = None
    p.axis.major_label_text_font_size = "11px"
    p.axis.axis_label_text_font_size = "12px"
    p.axis.axis_label_text_font_style = "normal"

    # Linear regression in log space (power-law fit in data space)
    log_pts = [(x, y) for x, y in zip(xs, ys, strict=True) if x > 0 and y > 0]
    if len(log_pts) >= 2:
        log_xs = np.log([pt[0] for pt in log_pts])
        log_ys = np.log([pt[1] for pt in log_pts])
        slope, intercept = np.polyfit(log_xs, log_ys, 1)
        x_min, x_max = min(x for x, _ in log_pts), max(x for x, _ in log_pts)
        reg_xs = [x_min, x_max]
        reg_ys = [np.exp(intercept) * x**slope for x in reg_xs]
        p.line(reg_xs, reg_ys, line_color="#ef4444", line_width=1.5, line_dash="dashed", alpha=0.8)

    p.scatter(
        "x",
        "y",
        source=source,
        size=9,
        fill_color="#1e293b",
        fill_alpha=0.6,
        line_color=None,
    )
    p.add_tools(
        HoverTool(
            tooltips=[
                ("Channel", "@label"),
                (x_label, "@x{0.0000}"),
                (y_label, "@y{0.0000}"),
                ("Subscribers", "@fans{0,0}"),
                ("Messages", "@msgs{0,0}"),
            ]
        )
    )

    script, div = components(p)
    return script, div


def _build_scatter_plots(graph_data: "GraphData") -> "dict[str, Any] | None":
    """Build all scatter plots and return shared resources + per-plot script/div pairs."""
    try:
        from bokeh.resources import INLINE
    except ImportError:
        return None

    plots = [
        (
            "in_degree_centrality",
            "out_degree_centrality",
            "In-degree centrality",
            "Out-degree centrality",
            "In-degree centrality counts how often a channel is cited by others; out-degree counts how often it cites others."
            " Channels on the diagonal amplify as much as they are amplified."
            " Top-left channels are pure sources (cited but do not cite back); bottom-right are pure amplifiers (cite many but are rarely cited)."
            " Outliers far from the diagonal reveal asymmetric roles in the network.",
        ),
        (
            "hits_hub",
            "hits_authority",
            "HITS Hub score",
            "HITS Authority score",
            "The HITS algorithm separates two complementary roles: authorities are channels whose content is worth citing,"
            " hubs are channels that consistently point to good authorities."
            " Top-right channels are both trusted sources and active amplifiers."
            " Top-left are pure authorities — original voices that others reference but that do not relay much themselves."
            " Bottom-right are pure hubs — aggregators or re-broadcasters that add little original content.",
        ),
        (
            "pagerank",
            "betweenness",
            "PageRank",
            "Betweenness centrality",
            "PageRank measures prestige through recursive amplification: being cited by important channels raises your score."
            " Betweenness centrality measures how often a channel sits on the shortest path between two others — a broker or bridge role."
            " High PageRank with low betweenness signals an influential channel that operates within a dense cluster."
            " High betweenness with lower PageRank reveals structural brokers: channels that connect otherwise separate parts of the network"
            " without necessarily being the most amplified voices.",
        ),
        (
            "pagerank",
            "bridging_centrality",
            "PageRank",
            "Bridging centrality",
            "Bridging centrality combines betweenness with neighbour-community diversity:"
            " a channel scores high only if it sits between many pairs of nodes AND its neighbours belong to different communities."
            " Comparing it to PageRank reveals whether influential channels are embedded within a single ideological cluster"
            " or actively connect across community boundaries."
            " High PageRank with low bridging indicates a powerful voice inside its own bubble;"
            " high bridging with moderate PageRank points to cross-community connectors that may be strategically important despite lower overall prestige.",
        ),
        (
            "betweenness",
            "bridging_centrality",
            "Betweenness centrality",
            "Bridging centrality",
            "Both measures capture broker roles, but with different definitions."
            " Betweenness is purely topological: it counts shortest paths regardless of community structure."
            " Bridging weights those paths by how much they cross community boundaries."
            " Channels near the diagonal are brokers in both senses."
            " High betweenness with low bridging reveals channels that are structural bottlenecks within a single community."
            " High bridging with lower betweenness identifies channels that connect communities even if they are not on many shortest paths overall.",
        ),
        (
            "pagerank",
            "katz_centrality",
            "PageRank",
            "Katz centrality",
            "Both PageRank and Katz centrality measure influence through the network's link structure, but with different assumptions."
            " PageRank discounts links from highly-connected nodes: a citation from a selective source counts more than one from a prolific forwarder."
            " Katz counts all paths with exponential decay by length, treating every incoming link equally regardless of the source's out-degree."
            " Channels well above the diagonal benefit from sheer volume of connections (grassroots amplification);"
            " channels below it owe their standing to endorsement by a few high-quality sources (elite endorsement).",
        ),
        (
            "harmonic_centrality",
            "in_degree_centrality",
            "Harmonic centrality",
            "In-degree centrality",
            "Harmonic centrality measures how quickly a channel can be reached from every other node in the network,"
            " capturing structural accessibility independent of direct links."
            " In-degree simply counts direct citations."
            " Channels high on both are well-cited and structurally central."
            " High harmonic with low in-degree reveals channels that are well-positioned in the network topology"
            " but receive few direct references — potential brokers whose influence operates through indirect paths."
            " High in-degree with low harmonic indicates channels that attract many direct citations but sit in a peripheral or isolated region of the graph.",
        ),
    ]

    built = []
    for x_key, y_key, x_label, y_label, description in plots:
        result = _build_scatter(graph_data, x_key, y_key, x_label, y_label)
        if result is not None:
            built.append(
                {
                    "title": f"{x_label} vs {y_label}",
                    "description": description,
                    "script": result[0],
                    "div": result[1],
                }
            )

    if not built:
        return None

    return {"resources": INLINE.render(), "plots": built}


def write_network_table_html(
    community_table_data: CommunityTableData,
    strategies: list[str],
    output_filename: str,
    graph_data: "GraphData | None" = None,
    seo: bool = False,
    project_title: str = "",
) -> None:
    def _fmt(val: float | None, decimals: int = 4) -> str:
        return "N/A" if val is None else f"{val:.{decimals}f}"

    summary = community_table_data["network_summary"]
    wcc_marker = " *" if not summary["path_on_full"] else ""
    summary_rows = []
    for label, value in _network_summary_rows(summary):
        if isinstance(value, float):
            display = _fmt(value)
        elif value is None:
            display = "N/A"
        else:
            display = str(value)
        summary_rows.append({"label": label, "value": display})

    modularity_rows = []
    for strategy_key in strategies:
        entry = community_table_data["strategies"].get(strategy_key)
        mod = entry["modularity"] if entry else None
        modularity_rows.append(
            {"strategy": strategy_key.capitalize(), "value": _fmt(mod) if mod is not None else "N/A"}
        )

    bokeh_resources = None
    bokeh_plots: list[dict[str, Any]] = []
    if graph_data is not None:
        scatter_data = _build_scatter_plots(graph_data)
        if scatter_data is not None:
            bokeh_resources = scatter_data["resources"]
            bokeh_plots = scatter_data["plots"]

    if seo:
        title = f"{project_title} | Network statistics" if project_title else "Network statistics"
        robots_meta = "index, follow"
    else:
        title = f"{project_title} | Network" if project_title else "Network"
        robots_meta = "noindex, nofollow"

    context = {
        "title": title,
        "robots_meta": robots_meta,
        "wcc_note_visible": not summary["path_on_full"],
        "summary_rows": summary_rows,
        "modularity_rows": modularity_rows,
        "wcc_marker": wcc_marker,
        "bokeh_resources": bokeh_resources,
        "bokeh_plots": bokeh_plots,
    }
    content = render_to_string("network/network_table.html", context)
    with open(output_filename, "w") as f:
        f.write(content)


def write_network_table_xlsx(
    community_table_data: CommunityTableData,
    strategies: list[str],
    output_filename: str,
    project_title: str = "",
) -> None:
    summary = community_table_data["network_summary"]
    wb = openpyxl.Workbook()
    if project_title:
        wb.properties.title = project_title

    ws = wb.active
    ws.title = "Network"
    ws.append(["Metric", "Value"])
    for cell in ws[1]:
        cell.font = Font(bold=True)
    for label, value in _network_summary_rows(summary):
        ws.append([label, value])
    if not summary["path_on_full"]:
        ws.append([])
        ws.append(["* Computed on the largest weakly connected component (undirected)"])

    ws.append([])
    ws.append(["Strategy", "Modularity"])
    for cell in ws[ws.max_row]:
        cell.font = Font(bold=True)
    for strategy_key in strategies:
        entry = community_table_data["strategies"].get(strategy_key)
        ws.append([strategy_key.capitalize(), entry["modularity"] if entry else None])

    wb.save(output_filename)


def write_community_table_xlsx(
    community_table_data: CommunityTableData,
    strategies: list[str],
    output_filename: str,
    project_title: str = "",
) -> None:
    _HEADERS = [
        "Community",
        "Color",
        "Nodes",
        "Internal Edges",
        "External Edges",
        "Density",
        "Reciprocity",
        "Avg Clustering",
        "Avg Path Length",
        "Diameter",
        "Channels",
    ]

    wb = openpyxl.Workbook()
    if project_title:
        wb.properties.title = project_title
    wb.remove(wb.active)  # no default sheet needed

    # One sheet per strategy
    for strategy_key in strategies:
        strategy_entry = community_table_data["strategies"].get(strategy_key)
        if not strategy_entry:
            continue
        rows = strategy_entry["rows"]
        ws = wb.create_sheet(title=strategy_key.capitalize()[:31])
        ws.append(_HEADERS)
        for cell in ws[1]:
            cell.font = Font(bold=True)
        for entry in rows:
            _community_id, _count, label, hex_color = entry["group"]
            hex_color = str(hex_color).lstrip("#")
            metrics = entry["metrics"]
            channels_str = ", ".join(c["label"] for c in entry.get("channels", []))
            ws.append(
                [
                    str(label),
                    f"#{hex_color}",
                    entry["node_count"],
                    metrics["internal_edges"],
                    metrics["external_edges"],
                    metrics["density"],
                    metrics["reciprocity"],
                    metrics["avg_clustering"],
                    metrics["avg_path_length"],
                    metrics["diameter"],
                    channels_str,
                ]
            )
            try:
                fill = PatternFill(start_color=hex_color.upper(), end_color=hex_color.upper(), fill_type="solid")
                ws.cell(row=ws.max_row, column=1).fill = fill
            except Exception:
                pass

    wb.save(output_filename)


def _metric_cell_dict(val: float | int | None, decimals: int, bg: str) -> dict:
    if val is None:
        return {"display": "N/A", "sort_value": "", "style": bg}
    if decimals == 0:
        return {"display": str(int(val)), "sort_value": str(int(val)), "style": bg}
    return {"display": f"{val:.{decimals}f}", "sort_value": str(val), "style": bg}


def write_community_table_html(
    community_table_data: CommunityTableData,
    strategies: list[str],
    output_filename: str,
    seo: bool = False,
    project_title: str = "",
) -> None:
    def _fmt(val: float | None, decimals: int = 4) -> str:
        return "N/A" if val is None else f"{val:.{decimals}f}"

    strategies_ctx = []
    for strategy_key in strategies:
        strategy_entry = community_table_data["strategies"].get(strategy_key)
        if not strategy_entry:
            continue
        precomputed_rows = strategy_entry["rows"]

        _hm_cols = {
            "node_count": [e["node_count"] for e in precomputed_rows],
            "internal_edges": [e["metrics"]["internal_edges"] for e in precomputed_rows],
            "external_edges": [e["metrics"]["external_edges"] for e in precomputed_rows],
            "density": [v for e in precomputed_rows if (v := e["metrics"].get("density")) is not None],
            "reciprocity": [v for e in precomputed_rows if (v := e["metrics"].get("reciprocity")) is not None],
            "avg_clustering": [v for e in precomputed_rows if (v := e["metrics"].get("avg_clustering")) is not None],
            "avg_path_length": [v for e in precomputed_rows if (v := e["metrics"].get("avg_path_length")) is not None],
            "diameter": [v for e in precomputed_rows if (v := e["metrics"].get("diameter")) is not None],
        }
        hm_ranges = {col: (min(vs), max(vs)) for col, vs in _hm_cols.items() if vs}

        def _hm(val: Any, col: str, _ranges: dict = hm_ranges) -> str:
            return _heatmap_bg(val, *_ranges[col]) if col in _ranges else ""

        rows_ctx = []
        for entry in precomputed_rows:
            _community_id, _count, label, hex_color = entry["group"]
            if not str(hex_color).startswith("#"):
                hex_color = f"#{hex_color}"
            m = entry["metrics"]
            nc = entry["node_count"]
            cells = [
                {"display": str(nc), "sort_value": str(nc), "style": _hm(nc, "node_count")},
                {
                    "display": str(m["internal_edges"]),
                    "sort_value": str(m["internal_edges"]),
                    "style": _hm(m["internal_edges"], "internal_edges"),
                },
                {
                    "display": str(m["external_edges"]),
                    "sort_value": str(m["external_edges"]),
                    "style": _hm(m["external_edges"], "external_edges"),
                },
                _metric_cell_dict(m["density"], 4, _hm(m["density"], "density")),
                _metric_cell_dict(m["reciprocity"], 4, _hm(m["reciprocity"], "reciprocity")),
                _metric_cell_dict(m["avg_clustering"], 4, _hm(m["avg_clustering"], "avg_clustering")),
                _metric_cell_dict(m["avg_path_length"], 4, _hm(m["avg_path_length"], "avg_path_length")),
                _metric_cell_dict(m["diameter"], 0, _hm(m["diameter"], "diameter")),
            ]
            rows_ctx.append(
                {
                    "label": str(label),
                    "hex_color": str(hex_color),
                    "cells": cells,
                    "channels": entry.get("channels", []),
                }
            )

        strategies_ctx.append(
            {
                "label": strategy_key.capitalize(),
                "h3_id": f"strategy-{strategy_key}",
                "rows": rows_ctx,
            }
        )

    if seo:
        title = f"{project_title} | Community statistics" if project_title else "Community statistics"
        robots_meta = "index, follow"
    else:
        title = f"{project_title} | Communities" if project_title else "Communities"
        robots_meta = "noindex, nofollow"

    context = {
        "title": title,
        "robots_meta": robots_meta,
        "strategies": strategies_ctx,
    }
    content = render_to_string("network/community_table.html", context)
    with open(output_filename, "w") as f:
        f.write(content)
