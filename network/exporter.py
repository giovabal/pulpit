import csv as _csv
import datetime
import html as _html
import json
import logging
import os
import re
import shutil
from math import sqrt
from typing import TYPE_CHECKING, Any

from django.conf import settings
from django.db.models import QuerySet

from network.community import (
    SBM_CONFIDENCE_BASE_KEY,
    canonical_strategy_key,
    sbm_confidence_display_label,
    sbm_confidence_key,
    strategy_display_label,
)
from network.measures._registry import role_companions
from network.utils import GraphData
from webapp.models import Channel
from webapp.utils.colors import parse_color, rgb_avg

import networkx as nx
from networkx.readwrite.gexf import GEXFWriter

if TYPE_CHECKING:
    from network.coordination import CoordinationResult

logger = logging.getLogger(__name__)

_ISOLATED_GRID_DIVISIONS: int = 200


def build_graph_data(
    graph: nx.DiGraph,
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
            "organization",
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
        # SBM(refine=MCMC) assignment-confidence companions — written onto the node data by
        # community detection (which runs before this serialisation), one parameter-suffixed
        # key per refined SBM instance.
        for key, value in node_data["data"].items():
            if key.startswith(SBM_CONFIDENCE_BASE_KEY):
                node_info[key] = value
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


def _patch_html_file(
    path: str,
    seo: bool,
    project_title: str,
    vertical_layout: bool = False,
    extra_layouts: "list[str] | None" = None,
    extra_layouts_3d: "list[str] | None" = None,
    node_count: int = 0,
    edge_count: int = 0,
    strategy_labels: "dict[str, str] | None" = None,
    data_dir: "str | None" = None,
) -> None:
    """Patch the robots meta tag, title, and layout flags in a static HTML file in-place."""
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
    repo_url = getattr(settings, "REPOSITORY_URL", "")
    app_version = getattr(settings, "APP_VERSION", "")
    if repo_url:
        content = content.replace("https://github.com/giovabal/pulpit", repo_url)
    # Accessibility: replace placeholders in the screen-reader-only network summary.
    content = content.replace("__NODE_COUNT__", f"{node_count:,}")
    content = content.replace("__EDGE_COUNT__", f"{edge_count:,}")
    vl_value = "true" if vertical_layout else "false"
    layouts_json = json.dumps(extra_layouts or [])
    layouts_3d_json = json.dumps(extra_layouts_3d or [])
    version_js = json.dumps(app_version)
    # Display names for the manual LABELGROUP<id> partitions, keyed by their lowercase community key
    # (labelgroup<id>). The static viewer (js/labels.js) folds these into STRATEGY_LABELS so the
    # colour-by selector and legend show the group's real name instead of a title-cased key. Escape
    # "</" so a group name containing "</script>" can't break out of this inline script.
    strategy_labels_json = json.dumps(strategy_labels or {}).replace("</", "<\\/")
    # A non-default data_dir turns the page into a viewer for a sibling data
    # directory (e.g. data_coordination/) — same JS, different payload.
    data_dir_js = f"window.DATA_DIR = {json.dumps(data_dir)}; " if data_dir else ""
    injection = (
        f"<script>{data_dir_js}window.VERTICAL_LAYOUT = {vl_value}; "
        f"window.EXTRA_LAYOUTS = {layouts_json}; "
        f"window.EXTRA_LAYOUTS_3D = {layouts_3d_json}; "
        f"window.STRATEGY_LABELS = {strategy_labels_json}; "
        f"window.APP_VERSION = {version_js};</script>\n"
    )
    for marker in ('<script src="js/', '<script type="module" src="js/'):
        idx = content.find(marker)
        if idx != -1:
            content = content[:idx] + injection + content[idx:]
            break
    else:
        # Neither marker found — the template's script-include format
        # diverged from what _patch_html_file knows about. The export will
        # be written without the window.* shims and the viewer JS will
        # behave as if every flag were unset (no vertical layout, no extra
        # layouts, label-group colour-by options shown by their raw key, blank
        # version chip). Log loud so the regression is caught instead of
        # silently shipping a broken export.
        logger.error(
            'Could not find a <script src="js/…"> marker in %s; window.* shims (VERTICAL_LAYOUT / '
            "EXTRA_LAYOUTS / EXTRA_LAYOUTS_3D / STRATEGY_LABELS / APP_VERSION) not injected.",
            path,
        )
    with open(path, "w") as f:
        f.write(content)


def apply_robots_to_graph_html(
    root_target: str,
    seo: bool,
    project_title: str = "",
    include_3d: bool = False,
    vertical_layout: bool = False,
    extra_layouts: "list[str] | None" = None,
    extra_layouts_3d: "list[str] | None" = None,
    node_count: int = 0,
    edge_count: int = 0,
    strategy_labels: "dict[str, str] | None" = None,
) -> None:
    """Patch the robots meta tag, title, and layout flags in the static graph HTML files after they are copied."""
    _patch_html_file(
        os.path.join(root_target, "graph.html"),
        seo,
        project_title,
        vertical_layout,
        extra_layouts,
        extra_layouts_3d,
        node_count=node_count,
        edge_count=edge_count,
        strategy_labels=strategy_labels,
    )
    if include_3d:
        _patch_html_file(
            os.path.join(root_target, "graph3d.html"),
            seo,
            project_title,
            vertical_layout,
            extra_layouts,
            extra_layouts_3d,
            node_count=node_count,
            edge_count=edge_count,
            strategy_labels=strategy_labels,
        )


_EXPORT_SKIP = frozenset({"id", "x", "y", "color", "pic", "activity_period"})


def _prepare_export_graph(graph: nx.DiGraph, graph_data: GraphData) -> nx.DiGraph:
    """Return an annotated copy of *graph* with node attributes from *graph_data*.

    Numeric attributes are type-harmonised per key: the GEXF writer declares each
    attribute's type from the first node serialized and ``write_graphml`` emits one
    ``<key>`` per (name, type) pair, so a column holding int on some nodes and float
    on others (e.g. a measure that yields exact 0 for isolated nodes) would produce
    schema-invalid GEXF or duplicate GraphML keys depending on DB row order.
    """
    g = graph.copy()
    node_by_id = {n["id"]: n for n in graph_data["nodes"]}
    float_keys: set[str] = set()
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
                if isinstance(value, float):
                    float_keys.add(key)
    for _node_id, attrs in g.nodes(data=True):
        for key in float_keys:
            value = attrs.get(key)
            if type(value) is int:  # bool is an int subclass — leave it alone
                attrs[key] = float(value)
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


_CSV_BASE_KEYS: frozenset[str] = frozenset({"in_deg", "out_deg", "fans", "messages_count"})


def _label_param_annotation(label: str) -> str:
    """Trailing ``" (param=value)"`` of a measure label, else ``""``.

    A role measure's base label ("Within-module z", "Brokerage") carries no parentheses, so the
    only parenthetical on its numeric column label is the per-instance parameter annotation —
    reused verbatim on the categorical companion columns so they stay aligned with their numeric
    column when a role measure is requested more than once.
    """
    idx = label.find(" (")
    return label[idx:] if idx != -1 else ""


def _role_companion_groups(measures_labels: list[tuple[str, str]]) -> list[tuple[dict, str]]:
    """Categorical companion column groups (the module role), one per role-measure instance,
    derived from each ``within_module_z*`` column."""
    groups: list[tuple[dict, str]] = []
    for key, label in measures_labels:
        comp = role_companions(key)
        if comp:
            groups.append((comp, _label_param_annotation(label)))
    return groups


def sbm_confidence_columns(graph_data: GraphData, strategies: list[str]) -> list[tuple[str, str]]:
    """(node_key, header) pairs of the SBM assignment-confidence companion columns.

    One per SBM instance in ``strategies`` whose nodes actually carry the suffixed
    ``sbm_confidence_*`` attribute — i.e. instances that ran with ``refine=MCMC``. Shared by
    the CSV and XLSX channel-table writers (the browser table derives the same columns
    client-side in channel_table.js).
    """
    cols: list[tuple[str, str]] = []
    for s in strategies:
        if canonical_strategy_key(s) not in ("sbm", "sbm_assortative"):
            continue
        key = sbm_confidence_key(s)
        if any(key in n for n in graph_data["nodes"]):
            cols.append((key, sbm_confidence_display_label(s)))
    return cols


def write_csv(
    graph_data: GraphData,
    edge_list: list[list],
    measures_labels: list[tuple[str, str]],
    strategies: list[str],
    output_dir: str,
) -> None:
    """Write nodes.csv and edges.csv to output_dir.

    nodes.csv mirrors channel_table.xlsx. A role measure requested with several community bases
    contributes one companion column group per instance, each carrying its parameter annotation.
    edges.csv columns: source_label, target_label, weight, weight_forwards, weight_mentions
    where weight_forwards and weight_mentions are the raw forward/mention counts.
    """
    os.makedirs(output_dir, exist_ok=True)

    label_by_id = {node["id"]: node.get("label") or node["id"] for node in graph_data["nodes"]}

    extra = [(k, lbl) for k, lbl in measures_labels if k not in _CSV_BASE_KEYS]
    pagerank_col = next(((k, lbl) for k, lbl in extra if k == "pagerank"), None)
    other_extra = [(k, lbl) for k, lbl in extra if k != "pagerank"]
    role_groups = _role_companion_groups(measures_labels)
    conf_cols = sbm_confidence_columns(graph_data, strategies)

    headers = ["Channel", "URL", "Label", "Users", "Messages", "Inbound", "Outbound"]
    if pagerank_col:
        headers.append(pagerank_col[1])
    headers += [lbl for _, lbl in other_extra]
    for comp, annot in role_groups:
        headers.append(comp["role_label"] + annot)
        headers += [cl + annot for cl in comp["count_labels"]]
    headers += [strategy_display_label(s) for s in strategies]
    headers += [lbl for _, lbl in conf_cols]
    headers += ["Activity start", "Activity end"]

    with open(os.path.join(output_dir, "nodes.csv"), "w", newline="", encoding="utf-8") as fh:
        writer = _csv.writer(fh)
        writer.writerow(headers)
        for node in sorted(graph_data["nodes"], key=lambda n: n.get("in_deg") or 0, reverse=True):
            communities = node.get("communities") or {}
            row: list = [
                node.get("label") or node["id"],
                node.get("url") or "",
                node.get("organization") or "",
                node.get("fans"),
                node.get("messages_count"),
                node.get("in_deg"),
                node.get("out_deg"),
            ]
            if pagerank_col:
                row.append(node.get(pagerank_col[0]))
            for key, _ in other_extra:
                row.append(node.get(key))
            for comp, _annot in role_groups:
                row.append(node.get(comp["role_key"]) or "")
                for count_key in comp["count_keys"]:
                    row.append(node.get(count_key))
            for s in strategies:
                row.append(communities.get(s, ""))
            for key, _ in conf_cols:
                row.append(node.get(key))
            row.append(node.get("activity_start") or "")
            row.append(node.get("activity_end") or "")
            writer.writerow(row)

    with open(os.path.join(output_dir, "edges.csv"), "w", newline="", encoding="utf-8") as fh:
        writer = _csv.writer(fh)
        writer.writerow(["source_label", "target_label", "weight", "weight_forwards", "weight_mentions"])
        for edge in edge_list:
            source_label = label_by_id.get(str(edge[0]), str(edge[0]))
            target_label = label_by_id.get(str(edge[1]), str(edge[1]))
            weight = edge[2]
            weight_forwards = edge[3]
            weight_mentions = edge[4]
            writer.writerow([source_label, target_label, weight, weight_forwards, weight_mentions])


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
    extra_positions: "dict[str, dict] | None" = None,
    extra_positions_3d: "dict[str, dict] | None" = None,
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

    if extra_positions and include_positions:
        # channel_position_<algo>.json — 2D extra layouts for the browser switcher (z=0 for 2D-only algos)
        for algo, pos in extra_positions.items():
            nodes_extra = []
            for n in graph_data["nodes"]:
                p = pos.get(n["id"])
                nodes_extra.append(
                    {
                        "id": n["id"],
                        "x": float(p[0]) if p is not None else 0.0,
                        "y": float(p[1]) if p is not None else 0.0,
                        "z": float(p[2]) if p is not None and len(p) > 2 else 0.0,
                    }
                )
            extra_payload = {"nodes": nodes_extra, "edges": graph_data["edges"]}
            with open(os.path.join(data_dir, f"channel_position_{algo}.json"), "w") as f:
                f.write(json.dumps(extra_payload))

    if extra_positions_3d and (include_positions or positions_3d is not None):
        # channel_position_3d_<algo>.json — 3D extra layouts for the 3D graph viewer
        for algo, pos in extra_positions_3d.items():
            nodes_extra = []
            for n in graph_data["nodes"]:
                p = pos.get(n["id"])
                nodes_extra.append(
                    {
                        "id": n["id"],
                        "x": float(p[0]) if p is not None else 0.0,
                        "y": float(p[1]) if p is not None else 0.0,
                        "z": float(p[2]) if p is not None and len(p) > 2 else 0.0,
                    }
                )
            extra_payload = {"nodes": nodes_extra, "edges": graph_data["edges"]}
            with open(os.path.join(data_dir, f"channel_position_3d_{algo}.json"), "w") as f:
                f.write(json.dumps(extra_payload))

    # channels.json — per-node metadata, computed measures, community assignments, measure labels.
    # The numeric measure keys come straight from measures_labels; each role measure's categorical
    # companion (the parameter-suffixed module_role label, kept in the payload / CSV / GEXF /
    # GraphML, not surfaced as a channel-table column) is derived per instance from its
    # within_module_z* column.
    node_keys: set[str] = {
        "id",
        "label",
        "organization",
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
    for measure_key, _label in measures_labels:
        comp = role_companions(measure_key)
        if comp:
            node_keys.add(comp["role_key"])
            node_keys.update(comp["count_keys"])
    # SBM(refine=MCMC) assignment-confidence companions, present on nodes when a refined SBM ran.
    node_keys |= {k for n in graph_data["nodes"] for k in n if k.startswith(SBM_CONFIDENCE_BASE_KEY)}
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
    edge_weight_strategy: str = "COMBINED",
    start_date: "datetime.date | None" = None,
    end_date: "datetime.date | None" = None,
    total_nodes: int = 0,
    total_edges: int = 0,
    community_distribution_threshold: int = 10,
    has_consensus_matrix: bool = False,
    community_backbone_alpha: float = 0.0,
) -> None:
    """Write data/meta.json with export metadata consumed by table preambles.

    The graph orientation is fixed to citing→cited (amplifier→source) — the
    citation convention that ``build_graph`` uses — so ``edge_direction`` is a
    constant string rather than a parameter.
    """
    _weight_labels = {
        "NONE": "unweighted (all edges equal)",
        "TOTAL": "raw forward + mention count",
        "PARTIAL_MESSAGES": "count divided by the citing channel's total messages",
        "PARTIAL_REFERENCES": "count divided by the citing channel's forwarding/citing messages",
    }
    payload: dict[str, object] = {
        "export_date": datetime.date.today().isoformat(),
        "project_title": project_title,
        "edge_direction": "edges point from citing channel to cited channel",
        "edge_weight_strategy": edge_weight_strategy,
        "edge_weight_label": _weight_labels.get(edge_weight_strategy, edge_weight_strategy),
        "start_date": start_date.isoformat() if start_date else None,
        "end_date": end_date.isoformat() if end_date else None,
        "total_nodes": total_nodes,
        "total_edges": total_edges,
        "community_distribution_threshold": community_distribution_threshold,
        "has_consensus_matrix": has_consensus_matrix,
        # α of the disparity-filter backbone the algorithmic community detections ran on
        # (0 = detection ran on the full graph). Surfaced in the community-table preamble.
        "community_backbone_alpha": community_backbone_alpha,
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
        "csv",
        "seo",
        "vertical_layout",
        "consensus_matrix",
        "structural_similarity",
        "behavioural_equivalence",
        "draw_dead_leaves",
        "timeline_step",
        "startdate",
        "enddate",
        "fa2_iterations",
        "layouts_2d",
        "layouts_3d",
        "diffusion_window",
        "community_distribution_threshold",
        "leiden_cpm_resolution",
        "community_backbone_alpha",
        "measures",
        "community_strategies",
        "network_stat_groups",
        "edge_weight_strategy",
        "include_mentions",
        "include_self_references",
        "channel_types",
        "channel_sources",
        "vacancy_measures",
        "vacancy_months_before",
        "vacancy_months_after",
        "vacancy_max_candidates",
        "robustness",
        "robustness_alpha",
        "robustness_strategies",
        "robustness_runs",
        "robustness_null",
        "robustness_null_model",
        "robustness_seed",
        "robustness_sample",
        "robustness_alpha_grid",
        "robustness_replay",
        "interest_structural",
        "interest_window_days",
        "interest_include_mentions",
        "coordination_2d",
        "coordination_3d",
        "coordination_window",
        "coordination_min_events",
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
        "pulpit_version": getattr(settings, "APP_VERSION", ""),
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


def _sanitize_nan_inf(obj):
    """Replace NaN and Inf floats with None so the result is strict-JSON safe.

    The robustness pipeline can legitimately emit NaN z-scores (when the null
    model's stddev collapses to zero) and Inf values from divisions; Python's
    json.dumps writes them as the literal tokens NaN / Infinity / -Infinity by
    default (allow_nan=True), but those are not valid JSON and JSON.parse()
    rejects them in browsers.
    """
    import math

    if isinstance(obj, float):
        return None if (math.isnan(obj) or math.isinf(obj)) else obj
    if isinstance(obj, dict):
        return {k: _sanitize_nan_inf(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_sanitize_nan_inf(v) for v in obj]
    if isinstance(obj, tuple):
        return tuple(_sanitize_nan_inf(v) for v in obj)
    return obj


def write_interest_structural_json(payload: dict, graph_dir: str) -> None:
    """Write data/interest_structural.json from compute_interest_structural."""
    data_dir = os.path.join(graph_dir, "data")
    os.makedirs(data_dir, exist_ok=True)
    with open(os.path.join(data_dir, "interest_structural.json"), "w") as f:
        f.write(json.dumps(_sanitize_nan_inf(payload), allow_nan=False))


def write_robustness_json(payload: dict, graph_dir: str) -> None:
    """Write data/robustness.json from the run_robustness payload."""
    data_dir = os.path.join(graph_dir, "data")
    os.makedirs(data_dir, exist_ok=True)
    with open(os.path.join(data_dir, "robustness.json"), "w") as f:
        # allow_nan=False ensures we fail loudly if any NaN/Inf slips through
        # the sanitizer rather than silently producing JSON the browser cannot
        # parse (cf. SyntaxError: Unexpected token 'N' on JSON.parse).
        f.write(json.dumps(_sanitize_nan_inf(payload), allow_nan=False))


_COORDINATION_DATA_DIR = "data_coordination"


def build_coordination_graph_data(
    graph_data: GraphData,
    coord_result: "CoordinationResult",
    positions: dict[str, tuple[float, float]],
) -> GraphData:
    """Serialize the coordination network, reusing the main graph's node dicts.

    Every participating channel is already a node of the main export (the
    coordination query runs over the citation graph's channel set), so its
    fully-enriched node dict — colour, communities, metadata, computed measures
    — is copied verbatim and only the position and the coordination scores are
    added. Each tie is emitted in both directions so the viewer renders and
    lists it as the mutual relation it is; edge colours follow the citation
    map's convention (dimmed average of the endpoint colours).
    """
    node_by_id = {n["id"]: n for n in graph_data["nodes"]}
    out: GraphData = {"nodes": [], "edges": []}
    for node_id in coord_result.node_ids:
        source = node_by_id.get(node_id)
        if source is None:  # defensive: scores for a channel outside the export
            continue
        node = dict(source)
        pos = positions.get(node_id)
        node["x"] = float(pos[0]) if pos is not None else 0.0
        node["y"] = float(pos[1]) if pos is not None else 0.0
        scores = coord_result.node_scores.get(node_id, {})
        node["coordination_strength"] = int(scores.get("strength", 0))
        node["coordination_partners"] = int(scores.get("partners", 0))
        node["coordination_ratio"] = float(scores.get("ratio", 0.0))
        out["nodes"].append(node)

    color_by_id = {n["id"]: n.get("color") or "" for n in out["nodes"]}
    index = 0
    for a, b, n_events in coord_result.edges:
        if a not in color_by_id or b not in color_by_id:
            continue
        avg = rgb_avg(parse_color(color_by_id[a]), parse_color(color_by_id[b]))
        color = ",".join(str(int(c * 0.75)) for c in avg)
        for source, target in ((a, b), (b, a)):
            out["edges"].append(
                {"source": source, "target": target, "weight": float(n_events), "color": color, "id": index}
            )
            index += 1
    return out


def write_coordination_files(
    coord_graph_data: GraphData,
    positions_3d: "dict[str, tuple[float, float, float]] | None",
    measures_labels: list[tuple[str, str]],
    graph_dir: str,
    *,
    communities_data: "dict[str, Any] | None" = None,
    dir_name: str = _COORDINATION_DATA_DIR,
) -> None:
    """Write a coordination data directory (``data_coordination/`` or a per-year sibling).

    Same file contract as ``data/`` (``channel_position.json``,
    ``channel_position_3d.json``, ``channels.json``, ``communities.json``), so
    the standard 2D/3D viewers render it unmodified once ``window.DATA_DIR``
    points here — the 2D viewer needs the first, third and fourth files, the
    3D viewer the last three. ``positions_3d`` is ``None`` when the 3D
    coordination map was not requested; ``channel_position_3d.json`` is then
    skipped, mirroring the main export's optional 3D positions file.
    ``communities_data`` is the strategy payload of the matching citation-graph
    scope (full range or one year), so community colouring and the legend work
    on the coordination map too. ``dir_name`` selects the directory: the
    default full-range ``data_coordination``, or ``data_coordination_<year>``
    for timeline years (the year switcher derives that name from the page's
    base directory).
    """
    data_dir = os.path.join(graph_dir, dir_name)
    os.makedirs(data_dir, exist_ok=True)

    position_payload = {
        "nodes": [{"id": n["id"], "x": n["x"], "y": n["y"]} for n in coord_graph_data["nodes"]],
        "edges": coord_graph_data["edges"],
    }
    with open(os.path.join(data_dir, "channel_position.json"), "w") as f:
        f.write(json.dumps(position_payload))

    if positions_3d is not None:
        nodes_3d = []
        for n in coord_graph_data["nodes"]:
            pos = positions_3d.get(n["id"])
            nodes_3d.append(
                {
                    "id": n["id"],
                    "x": float(pos[0]) if pos is not None else 0.0,
                    "y": float(pos[1]) if pos is not None else 0.0,
                    "z": float(pos[2]) if pos is not None else 0.0,
                }
            )
        with open(os.path.join(data_dir, "channel_position_3d.json"), "w") as f:
            f.write(json.dumps({"nodes": nodes_3d, "edges": coord_graph_data["edges"]}))

    channels_payload = {
        "nodes": coord_graph_data["nodes"],
        "measures": measures_labels,
        "total_pages_count": len(coord_graph_data["nodes"]),
    }
    with open(os.path.join(data_dir, "channels.json"), "w") as f:
        f.write(json.dumps(channels_payload))

    with open(os.path.join(data_dir, "communities.json"), "w") as f:
        f.write(json.dumps({"strategies": communities_data or {}}))


def write_coordination_timeline_json(timeline_entries: list[dict], graph_dir: str) -> None:
    """Write ``data_coordination/timeline.json`` — the coordination map's year switcher.

    Lists only the years whose per-year coordination network survived the
    thresholds (``has_coordination``), so the switcher never offers a year
    whose data directory does not exist. Same shape as ``data/timeline.json``
    (the viewers read ``year`` and ``has_graph``).
    """
    data_dir = os.path.join(graph_dir, _COORDINATION_DATA_DIR)
    os.makedirs(data_dir, exist_ok=True)
    years = [
        {
            "year": e["year"],
            "nodes": e.get("coordination_nodes", 0),
            "edges": e.get("coordination_ties", 0),
            "has_graph": True,
        }
        for e in timeline_entries
        if e.get("has_coordination")
    ]
    with open(os.path.join(data_dir, "timeline.json"), "w") as f:
        f.write(json.dumps({"years": years}))


_COORD_DESC_2D = (
    "An interactive map of temporal co-forwarding coordination: Telegram channels linked when they "
    "repeatedly forwarded the same origin message within a short time window."
)
_COORD_DESC_3D = "An interactive 3D map of temporal co-forwarding coordination between Telegram channels."


def write_coordination_pages(
    root_target: str,
    *,
    seo: bool,
    project_title: str = "",
    vertical_layout: bool = False,
    node_count: int = 0,
    tie_count: int = 0,
    strategy_labels: "dict[str, str] | None" = None,
    include_2d: bool = True,
    include_3d: bool = True,
) -> None:
    """Write ``coordination.html`` and/or ``coordination3d.html`` into the export root.

    ``include_2d`` / ``include_3d`` mirror the ``--coordination-2d`` /
    ``--coordination-3d`` output toggles. Each page is the pristine map
    template re-pointed at ``data_coordination/`` via ``window.DATA_DIR``, with
    titles and descriptions reworded for the coordination layer. ``tie_count``
    is the number of *unordered* pairs — the figure quoted in the
    screen-reader summary ("mutual co-forwarding ties"). No extra layouts are
    advertised (FA2 only), so the layout switcher stays hidden; the year
    switcher appears only when ``data_coordination/timeline.json`` exists.
    """
    map_src = str(settings.BASE_DIR / "webapp_engine" / "map")
    coord_title = f"{project_title} — Coordination" if project_title else "Co-forwarding coordination"
    page_specs = (
        (
            include_2d,
            "graph.html",
            "coordination.html",
            "An interactive force-directed network map of Telegram channels, "
            "showing connections through forwards and references.",
            _COORD_DESC_2D,
            "A map for Telegram channels",
            "Co-forwarding coordination map",
        ),
        (
            include_3d,
            "graph3d.html",
            "coordination3d.html",
            "An interactive 3D force-directed network map of Telegram channels.",
            _COORD_DESC_3D,
            "Pulpit project — 3D map",
            "Co-forwarding coordination — 3D map",
        ),
    )
    for included, src_name, dst_name, desc_old, desc_new, title_old, title_new in page_specs:
        if not included:
            continue
        src_path = os.path.join(map_src, src_name)
        dst_path = os.path.join(root_target, dst_name)
        try:
            with open(src_path) as f:
                content = f.read()
        except OSError as e:
            logger.warning("Could not read map template %s: %s", src_path, e)
            continue
        content = content.replace(desc_old, desc_new)
        content = content.replace(title_old, title_new)
        content = content.replace(
            "</strong> connections between them", "</strong> mutual co-forwarding ties between them"
        )
        with open(dst_path, "w") as f:
            f.write(content)
        _patch_html_file(
            dst_path,
            seo,
            coord_title,
            vertical_layout=vertical_layout,
            extra_layouts=[],
            extra_layouts_3d=[],
            node_count=node_count,
            edge_count=tie_count,
            strategy_labels=strategy_labels,
            data_dir=f"{_COORDINATION_DATA_DIR}/",
        )


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
