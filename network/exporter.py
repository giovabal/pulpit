import datetime
import html as _html
import json
import logging
import os
import shutil
from math import log, sqrt
from typing import Any

from django.conf import settings
from django.db.models import Count, Max, Min, Q, QuerySet

from webapp.models import Channel, Message

import networkx as nx
import openpyxl
from openpyxl.styles import Font

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
            "x": float(pos[0]),
            "y": float(pos[1]),
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


def apply_robots_to_graph_html(root_target: str, seo: bool) -> None:
    """Patch the robots meta tag in the static index.html after it is copied."""
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
    total_channels: int,
    output_filename: str,
    accessory_filename: str,
) -> None:
    with open(output_filename, "w") as outputfile:
        outputfile.write(json.dumps(graph_data))

    accessory_payload: dict[str, Any] = {
        "communities": communities_data,
        "measures": measures_labels,
        "total_pages_count": total_channels,
    }
    with open(accessory_filename, "w") as accessoryfile:
        accessoryfile.write(json.dumps(accessory_payload))


def copy_channel_media(channel_qs: QuerySet[Channel], root_target: str) -> None:
    for (username,) in channel_qs.filter(username__gt="").values_list("username"):
        src = os.path.join(settings.MEDIA_ROOT, "channels", username, "profile")
        dst = os.path.join(root_target, "channels", username, "profile")
        try:
            shutil.copytree(src, dst)
        except FileNotFoundError:
            pass
        except OSError as e:
            logger.warning("Could not copy media for channel %s: %s", username, e)


_BASE_MEASURE_KEYS: frozenset[str] = frozenset({"in_deg", "out_deg", "fans", "messages_count"})

_SORT_TABLE_JS = """
var tables = document.querySelectorAll("table.sortable"), table, thead, headers, i, j;
for (i = 0; i < tables.length; i++) {
    table = tables[i];
    if (thead = table.querySelector("thead")) {
        headers = thead.querySelectorAll("th");
        for (j = 0; j < headers.length; j++) {
            headers[j].innerHTML = "<a href='#'>" + headers[j].innerText + "</a>";
        }
        thead.addEventListener("click", sortTableFunction(table));
    }
}
function sortTableFunction(table) {
    return function(ev) {
        if (ev.target.tagName.toLowerCase() == 'a') {
            var header = ev.target.parentNode;
            var currentDirection = header.getAttribute('data-sort-direction');
            var direction = currentDirection === 'desc' ? 'asc' : 'desc';
            var siblingHeaders = header.parentNode.children;
            for (var i = 0; i < siblingHeaders.length; i++) {
                if (siblingHeaders[i] !== header) siblingHeaders[i].removeAttribute('data-sort-direction');
            }
            header.setAttribute('data-sort-direction', direction);
            sortRows(table, siblingIndex(header), direction);
            ev.preventDefault();
        }
    };
}
function siblingIndex(node) {
    var count = 0;
    while (node = node.previousElementSibling) count++;
    return count;
}
function sortRows(table, columnIndex, direction) {
    var rows = table.querySelectorAll("tbody tr"),
        sel  = "thead th:nth-child(" + (columnIndex + 1) + ")",
        sel2 = "td:nth-child(" + (columnIndex + 1) + ")",
        classList = table.querySelector(sel).classList,
        values = [], cls = "", sortDirection = direction || "asc", allNum = true, val, index, node;
    if (classList) {
        if (classList.contains("date")) cls = "date";
        else if (classList.contains("number")) cls = "number";
    }
    for (index = 0; index < rows.length; index++) {
        node = rows[index].querySelector(sel2);
        val = node.getAttribute("data-sort-value");
        if (val === null || val === "") val = node.innerText;
        var numericVal = parseFloat(val);
        if (!Number.isNaN(numericVal) && isFinite(numericVal)) val = numericVal; else allNum = false;
        values.push({ value: val, row: rows[index] });
    }
    if (cls == "" && allNum) cls = "number";
    if (cls == "number") values.sort(function(a, b) { return a.value - b.value; });
    else if (cls == "date") values.sort(function(a, b) { return Date.parse(a.value) - Date.parse(b.value); });
    else values.sort(function(a, b) {
        var ta = (a.value + "").toUpperCase(), tb = (b.value + "").toUpperCase();
        return ta < tb ? -1 : ta > tb ? 1 : 0;
    });
    if (sortDirection === "desc") values = values.reverse();
    for (var idx = 0; idx < values.length; idx++) table.querySelector("tbody").appendChild(values[idx].row);
}
"""


def write_table_html(
    graph_data: GraphData,
    measures_labels: list[tuple[str, str]],
    strategies: list[str],
    output_filename: str,
    seo: bool = False,
) -> None:
    extra = [(k, lbl) for k, lbl in measures_labels if k not in _BASE_MEASURE_KEYS]
    pagerank_col = next(((k, lbl) for k, lbl in extra if k == "pagerank"), None)
    other_extra = [(k, lbl) for k, lbl in extra if k != "pagerank"]
    nodes = sorted(graph_data["nodes"], key=lambda n: n.get("in_deg") or 0, reverse=True)

    pagerank_th = f'<th class="number">{_html.escape(pagerank_col[1])}</th>' if pagerank_col else ""
    other_extra_ths = "".join(f'<th class="number">{_html.escape(lbl)}</th>' for _, lbl in other_extra)
    strategy_ths = "".join(f"<th>{_html.escape(s.capitalize())}</th>" for s in strategies)
    thead = (
        "<thead><tr>"
        "<th>Channel</th>"
        '<th class="number">Users</th>'
        '<th class="number">Messages</th>'
        '<th class="number">Inbound</th>'
        '<th class="number">Outbound</th>' + pagerank_th + other_extra_ths + strategy_ths + "<th>Activity start</th>"
        "<th>Activity end</th>"
        "</tr></thead>"
    )

    def _num_cell(val: Any) -> str:
        sv = val if val is not None else ""
        disp = str(val) if val is not None else ""
        return f'<td data-sort-value="{sv}">{disp}</td>'

    def _float_cell(val: Any) -> str:
        if val is None:
            return '<td data-sort-value=""></td>'
        disp = f"{val:.4f}" if isinstance(val, float) else str(val)
        return f'<td data-sort-value="{val}">{disp}</td>'

    rows = []
    for node in nodes:
        label = _html.escape(node.get("label") or node["id"])
        url = node.get("url") or ""
        name_cell = (
            f'<td><a href="{url}" target="_blank" rel="noopener noreferrer">{label}</a></td>'
            if url
            else f"<td>{label}</td>"
        )
        cells = [name_cell]
        for key in ("fans", "messages_count", "in_deg", "out_deg"):
            cells.append(_num_cell(node.get(key)))
        if pagerank_col:
            cells.append(_float_cell(node.get(pagerank_col[0])))
        for key, _ in other_extra:
            cells.append(_float_cell(node.get(key)))
        communities = node.get("communities") or {}
        for s in strategies:
            cells.append(f"<td>{_html.escape(str(communities.get(s, '')))}</td>")
        cells.append(f"<td>{_html.escape(node.get('activity_start') or '')}</td>")
        cells.append(f"<td>{_html.escape(node.get('activity_end') or '')}</td>")
        rows.append("<tr>" + "".join(cells) + "</tr>\n")

    if seo:
        _title = "Channel network data"
        _robots = '<meta name="robots" content="index, follow">'
        _description = (
            f'<meta name="description" content="Network data for {len(nodes)} Telegram channels, '
            'including activity metrics, inbound and outbound connections, and community assignments.">'
        )
    else:
        _title = "Channels"
        _robots = '<meta name="robots" content="noindex, nofollow">'
        _description = ""

    content = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{_title}</title>
  {_robots}
  {_description}
  <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.8/dist/css/bootstrap.min.css" rel="stylesheet" integrity="sha384-sRIl4kxILFvY47J16cr9ZwB07vP4J8+LH7qKQnuqkuIAvNWLzeN8tE5YBujZqJLB" crossorigin="anonymous">
  <link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/bootstrap-icons@1.13.1/font/bootstrap-icons.min.css">
  <style>
    th a {{ text-decoration: none; color: inherit; }}
    th[data-sort-direction="asc"] a::after {{ content: " ▲"; }}
    th[data-sort-direction="desc"] a::after {{ content: " ▼"; }}
  </style>
</head>
<body>
  <div class="container-fluid py-3">
    <div class="d-flex justify-content-between align-items-start mb-2">
      <h2 class="mb-0">Channels</h2>
      <a href="index.html" class="btn btn-outline-secondary btn-sm"><i class="bi bi-diagram-3"></i> Back to map</a>
    </div>
    <p class="text-muted">{len(nodes)} channels. Click column headers to sort.</p>
    <div class="table-responsive">
      <table class="table table-striped table-bordered table-hover table-sm sortable">
        {thead}
        <tbody>
{"".join(rows)}        </tbody>
      </table>
    </div>
  </div>
  <script>{_SORT_TABLE_JS}  </script>
</body>
</html>"""
    with open(output_filename, "w") as f:
        f.write(content)


def write_table_xls(
    graph_data: GraphData,
    measures_labels: list[tuple[str, str]],
    strategies: list[str],
    output_filename: str,
) -> None:
    extra = [(k, lbl) for k, lbl in measures_labels if k not in _BASE_MEASURE_KEYS]
    pagerank_col = next(((k, lbl) for k, lbl in extra if k == "pagerank"), None)
    other_extra = [(k, lbl) for k, lbl in extra if k != "pagerank"]
    nodes = sorted(graph_data["nodes"], key=lambda n: n.get("in_deg") or 0, reverse=True)

    wb = openpyxl.Workbook()
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
