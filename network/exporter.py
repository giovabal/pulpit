import datetime
import html as _html
import json
import logging
import os
import re
import shutil
from math import sqrt
from typing import Any

from django.conf import settings
from django.db.models import QuerySet

from network.utils import GraphData
from webapp.models import Channel

import networkx as nx
from networkx.readwrite.gexf import GEXFWriter

logger = logging.getLogger(__name__)

_ISOLATED_GRID_DIVISIONS: int = 200


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
            "is_private",
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


def find_main_component(graph: nx.DiGraph) -> set[str]:
    return max(nx.weakly_connected_components(graph), key=len, default=set())


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
        map_src = str(settings.BASE_DIR / "webapp_engine" / "map")
        shutil.copytree(map_src, root_target, dirs_exist_ok=True)
    except OSError as e:
        logger.warning("Could not copy map template to %s: %s", root_target, e)


def _patch_html_file(path: str, seo: bool, project_title: str, vertical_layout: bool = False) -> None:
    """Patch the robots meta tag, title, and layout flag in a static HTML file in-place."""
    if not os.path.exists(path):
        return
    with open(path) as f:
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
    vl_value = "true" if vertical_layout else "false"
    injection = f"<script>window.VERTICAL_LAYOUT = {vl_value};</script>\n"
    for marker in ('<script src="js/', '<script type="module" src="js/'):
        idx = content.find(marker)
        if idx != -1:
            content = content[:idx] + injection + content[idx:]
            break
    with open(path, "w") as f:
        f.write(content)


def apply_robots_to_graph_html(
    root_target: str, seo: bool, project_title: str = "", include_3d: bool = False, vertical_layout: bool = False
) -> None:
    """Patch the robots meta tag, title, and layout flag in the static graph HTML files after they are copied."""
    _patch_html_file(os.path.join(root_target, "graph.html"), seo, project_title, vertical_layout)
    if include_3d:
        _patch_html_file(os.path.join(root_target, "graph3d.html"), seo, project_title, vertical_layout)


_EXPORT_SKIP = frozenset({"id", "x", "y", "color", "pic", "activity_period"})


def _prepare_export_graph(graph: nx.DiGraph, graph_data: GraphData) -> nx.DiGraph:
    """Return an annotated copy of *graph* with node attributes from *graph_data*."""
    g = graph.copy()
    node_by_id = {n["id"]: n for n in graph_data["nodes"]}
    for node_id in g.nodes():
        node = node_by_id.get(node_id)
        if node is None:
            continue
        attrs = g.nodes[node_id]
        attrs.pop("data", None)
        for key, value in node.items():
            if key in _EXPORT_SKIP:
                continue
            if key == "communities":
                for strategy, label in (value or {}).items():
                    if label is not None:
                        attrs[f"community_{strategy}"] = str(label)
            elif value is not None:
                attrs[key] = value
    return g


def write_gexf(graph: nx.DiGraph, graph_data: GraphData, output_filename: str) -> None:
    """Write a GEXF file with all computed node attributes embedded."""
    g = _prepare_export_graph(graph, graph_data)
    writer = GEXFWriter()
    meta = writer.xml.find("meta")
    if meta is not None:
        creator_el = meta.find("creator")
        if creator_el is not None:
            creator_el.text = "Pulpit"
    writer.add_graph(g)
    with open(output_filename, "wb") as fh:
        writer.write(fh)


def write_graphml(graph: nx.DiGraph, graph_data: GraphData, output_filename: str) -> None:
    """Write a GraphML file with all computed node attributes embedded."""
    g = _prepare_export_graph(graph, graph_data)
    nx.write_graphml(g, output_filename)


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
    graph_dir: str,
    include_positions: bool = True,
    positions_3d: dict | None = None,
) -> None:
    data_dir = os.path.join(graph_dir, "data")
    os.makedirs(data_dir, exist_ok=True)

    if include_positions:
        # channel_position.json — spatial layout + edges
        position_payload = {
            "nodes": [{"id": n["id"], "x": n["x"], "y": n["y"]} for n in graph_data["nodes"]],
            "edges": graph_data["edges"],
        }
        with open(os.path.join(data_dir, "channel_position.json"), "w") as f:
            f.write(json.dumps(position_payload))

    if positions_3d is not None:
        # channel_position_3d.json — 3D spatial layout + edges
        nodes_3d = []
        for n in graph_data["nodes"]:
            pos = positions_3d.get(n["id"])
            nodes_3d.append(
                {
                    "id": n["id"],
                    "x": float(pos[0]) if pos is not None else 0.0,
                    "y": float(pos[1]) if pos is not None else 0.0,
                    "z": float(pos[2]) if pos is not None else 0.0,
                }
            )
        position_3d_payload = {"nodes": nodes_3d, "edges": graph_data["edges"]}
        with open(os.path.join(data_dir, "channel_position_3d.json"), "w") as f:
            f.write(json.dumps(position_3d_payload))

    # channels.json — per-node metadata, computed measures, community assignments, measure labels
    node_keys: set[str] = {
        "id",
        "label",
        "color",
        "pic",
        "url",
        "activity_period",
        "fans",
        "in_deg",
        "is_lost",
        "messages_count",
        "out_deg",
        "activity_start",
        "activity_end",
    } | {k for k, _ in measures_labels}
    channels_payload: dict[str, Any] = {
        "nodes": [
            {**{k: n[k] for k in node_keys if k in n}, "communities": n.get("communities", {})}
            for n in graph_data["nodes"]
        ],
        "measures": measures_labels,
        "total_pages_count": channel_qs.count(),
    }
    with open(os.path.join(data_dir, "channels.json"), "w") as f:
        f.write(json.dumps(channels_payload))

    # communities.json — strategy group definitions (metrics rows added later by write_community_metrics_json)
    with open(os.path.join(data_dir, "communities.json"), "w") as f:
        f.write(json.dumps({"strategies": communities_data}))


def write_meta_json(
    graph_dir: str,
    *,
    project_title: str = "",
    reversed_edges: bool = True,
    edge_weight_strategy: str = "COMBINED",
    start_date: "datetime.date | None" = None,
    end_date: "datetime.date | None" = None,
    total_nodes: int = 0,
    total_edges: int = 0,
    community_distribution_threshold: int = 10,
    has_consensus_matrix: bool = False,
) -> None:
    """Write data/meta.json with export metadata consumed by table preambles."""
    _weight_labels = {
        "NONE": "unweighted (all edges equal)",
        "TOTAL": "raw forward + mention count",
        "PARTIAL_MESSAGES": "count divided by total messages",
        "PARTIAL_REFERENCES": "count divided by forwarding/citing messages",
    }
    edge_direction = (
        "edges point from citing channel to cited channel"
        if reversed_edges
        else "edges point from cited channel to citing channel"
    )
    payload: dict[str, object] = {
        "export_date": datetime.date.today().isoformat(),
        "project_title": project_title,
        "reversed_edges": reversed_edges,
        "edge_direction": edge_direction,
        "edge_weight_strategy": edge_weight_strategy,
        "edge_weight_label": _weight_labels.get(edge_weight_strategy, edge_weight_strategy),
        "start_date": start_date.isoformat() if start_date else None,
        "end_date": end_date.isoformat() if end_date else None,
        "total_nodes": total_nodes,
        "total_edges": total_edges,
        "community_distribution_threshold": community_distribution_threshold,
        "has_consensus_matrix": has_consensus_matrix,
    }
    data_dir = os.path.join(graph_dir, "data")
    with open(os.path.join(data_dir, "meta.json"), "w") as f:
        f.write(json.dumps(payload))


def write_summary_json(
    graph_dir: str,
    name: "str | None",
    options: dict,
    nodes: int,
    edges: int,
) -> None:
    """Write summary.json at the export root with name, timestamp, result counts, and all CLI options."""
    _OPTION_KEYS = (
        "graph",
        "graph_3d",
        "html",
        "xlsx",
        "gexf",
        "graphml",
        "seo",
        "vertical_layout",
        "consensus_matrix",
        "draw_dead_leaves",
        "timeline_step",
        "startdate",
        "enddate",
        "fa2_iterations",
        "recency_weights",
        "spreading_runs",
        "community_distribution_threshold",
        "leiden_coarse_resolution",
        "leiden_fine_resolution",
        "mcl_inflation",
        "measures",
        "community_strategies",
        "network_stat_groups",
        "edge_weight_strategy",
        "channel_types",
        "channel_groups",
        "vacancy_measures",
        "vacancy_months_before",
        "vacancy_months_after",
        "vacancy_max_candidates",
        "vacancy_ppr_alpha",
    )
    opts: dict = {}
    for key in _OPTION_KEYS:
        val = options.get(key)
        if val is None:
            opts[key] = None
        elif isinstance(val, bool):
            opts[key] = val
        else:
            opts[key] = val if val != "" else None
    payload = {
        "name": name,
        "created_at": datetime.datetime.now().isoformat(timespec="seconds"),
        "nodes": nodes,
        "edges": edges,
        "options": opts,
    }
    os.makedirs(graph_dir, exist_ok=True)
    with open(os.path.join(graph_dir, "summary.json"), "w") as f:
        f.write(json.dumps(payload, indent=2))


def write_vacancy_analysis_json(payload: dict, graph_dir: str) -> None:
    """Write data/vacancy_analysis.json from the compute_vacancy_analysis payload."""
    data_dir = os.path.join(graph_dir, "data")
    os.makedirs(data_dir, exist_ok=True)
    with open(os.path.join(data_dir, "vacancy_analysis.json"), "w") as f:
        f.write(json.dumps(payload))


def copy_channel_media(channel_qs: QuerySet[Channel], root_target: str) -> None:
    for username, telegram_id in channel_qs.values_list("username", "telegram_id"):
        channel_dir = username or str(telegram_id)
        src = os.path.join(settings.MEDIA_ROOT, "channels", channel_dir, "profile")
        dst = os.path.join(root_target, "media", "channels", channel_dir, "profile")
        try:
            shutil.copytree(src, dst, dirs_exist_ok=True)
        except FileNotFoundError:
            pass
        except OSError as e:
            logger.warning("Could not copy media for channel %s: %s", channel_dir, e)
