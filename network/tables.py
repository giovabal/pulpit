import json
import logging
import os
import shutil
from typing import Any

from django.template.loader import render_to_string

from network.community_stats import network_summary_rows
from network.utils import CommunityTableData, GraphData

import openpyxl
from openpyxl.styles import Font, PatternFill

logger = logging.getLogger(__name__)

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


def write_table_html(
    graph_data: GraphData,
    output_filename: str,
    seo: bool = False,
    project_title: str = "",
) -> None:
    n = len(graph_data["nodes"])
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
    year_data: "list[tuple[int, GraphData]] | None" = None,
) -> None:
    extra = [(k, lbl) for k, lbl in measures_labels if k not in _BASE_MEASURE_KEYS]
    pagerank_col = next(((k, lbl) for k, lbl in extra if k == "pagerank"), None)
    other_extra = [(k, lbl) for k, lbl in extra if k != "pagerank"]

    headers = ["Channel", "URL", "Users", "Messages", "Inbound", "Outbound"]
    if pagerank_col:
        headers.append(pagerank_col[1])
    headers += [lbl for _, lbl in other_extra]
    headers += [s.capitalize() for s in strategies]
    headers += ["Activity start", "Activity end"]

    def _fill(ws: Any, gd: GraphData) -> None:
        ws.append(headers)
        for cell in ws[1]:
            cell.font = Font(bold=True)
        for node in sorted(gd["nodes"], key=lambda n: n.get("in_deg") or 0, reverse=True):
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

    wb = openpyxl.Workbook()
    wb.properties.creator = "Pulpit"
    if project_title:
        wb.properties.title = project_title
    ws = wb.active
    ws.title = "All" if year_data else "Channels"
    _fill(ws, graph_data)

    if year_data:
        for yr, yr_gd in year_data:
            _fill(wb.create_sheet(title=str(yr)), yr_gd)

    wb.save(output_filename)


def write_network_metrics_json(
    community_table_data: CommunityTableData,
    strategies: list[str],
    graph_dir: str,
) -> None:
    def _fmt(val: float | None, decimals: int = 4) -> str:
        return "—" if val is None else f"{val:.{decimals}f}"

    data_dir = os.path.join(graph_dir, "data")
    summary = community_table_data["network_summary"]
    summary_rows = []
    for label, value, group in network_summary_rows(summary):
        if isinstance(value, float):
            display = _fmt(value)
        elif value is None:
            display = "—"
        else:
            display = str(value)
        summary_rows.append({"label": label, "value": display, "group": group})

    modularity_rows = []
    for strategy_key in strategies:
        entry = community_table_data["strategies"].get(strategy_key)
        mod = entry["modularity"] if entry else None
        icr = entry.get("inter_community_edge_ratio") if entry else None
        mei = entry.get("mean_ei_index") if entry else None
        modularity_rows.append(
            {
                "strategy": strategy_key,
                "modularity": _fmt(mod) if mod is not None else "—",
                "inter_community_ratio": _fmt(icr) if icr is not None else "—",
                "mean_ei": _fmt(mei) if mei is not None else "—",
            }
        )

    payload = {
        "wcc_note_visible": not summary["path_on_full"],
        "scc_note_visible": (
            summary.get("avg_path_length_directed") is not None and not summary.get("scc_path_on_full", True)
        ),
        "summary_rows": summary_rows,
        "modularity_rows": modularity_rows,
    }
    with open(os.path.join(data_dir, "network_metrics.json"), "w") as f:
        f.write(json.dumps(payload))


def write_network_table_html(
    output_filename: str,
    seo: bool = False,
    project_title: str = "",
) -> None:
    if seo:
        title = f"{project_title} | Network statistics" if project_title else "Network statistics"
        robots_meta = "index, follow"
    else:
        title = f"{project_title} | Network" if project_title else "Network"
        robots_meta = "noindex, nofollow"

    context = {"title": title, "robots_meta": robots_meta}
    content = render_to_string("network/network_table.html", context)
    with open(output_filename, "w") as f:
        f.write(content)


def write_network_table_xlsx(
    community_table_data: CommunityTableData,
    strategies: list[str],
    output_filename: str,
    project_title: str = "",
    year_data: "list[tuple[int, CommunityTableData]] | None" = None,
) -> None:
    def _fill(ws: Any, ctd: CommunityTableData) -> None:
        summary = ctd["network_summary"]
        ws.append(["Metric", "Value"])
        for cell in ws[1]:
            cell.font = Font(bold=True)
        for label, value, _group in network_summary_rows(summary):
            ws.append([label, value])
        if not summary["path_on_full"]:
            ws.append([])
            ws.append(["† Computed on the largest weakly connected component (undirected)"])
        if summary.get("avg_path_length_directed") is not None and not summary.get("scc_path_on_full", True):
            ws.append([])
            ws.append(["‡ Computed on the largest strongly connected component (directed)"])
        ws.append([])
        ws.append(["Strategy", "Modularity"])
        for cell in ws[ws.max_row]:
            cell.font = Font(bold=True)
        for strategy_key in strategies:
            entry = ctd["strategies"].get(strategy_key)
            ws.append([strategy_key.capitalize(), entry["modularity"] if entry else None])

    wb = openpyxl.Workbook()
    wb.properties.creator = "Pulpit"
    if project_title:
        wb.properties.title = project_title
    ws = wb.active
    ws.title = "All" if year_data else "Network"
    _fill(ws, community_table_data)

    if year_data:
        for yr, yr_ctd in year_data:
            _fill(wb.create_sheet(title=str(yr)), yr_ctd)

    wb.save(output_filename)


_COMPARE_RENAMES: dict[str, str] = {
    "graph.html": "graph_2.html",
    "graph3d.html": "graph3d_2.html",
    "channel_table.html": "channel_table_2.html",
    "network_table.html": "network_table_2.html",
    "community_table.html": "community_table_2.html",
    "consensus_matrix.html": "consensus_matrix_2.html",
    "channel_table.xlsx": "channel_table_2.xlsx",
    "network_table.xlsx": "network_table_2.xlsx",
    "community_table.xlsx": "community_table_2.xlsx",
}

# Ordered so that graph3d.html is replaced before graph.html (avoid partial match)
_HTML_LINK_RENAMES: list[tuple[str, str]] = [
    ("graph3d.html", "graph3d_2.html"),
    ("graph.html", "graph_2.html"),
    ("channel_table.html", "channel_table_2.html"),
    ("network_table.html", "network_table_2.html"),
    ("community_table.html", "community_table_2.html"),
    ("consensus_matrix.html", "consensus_matrix_2.html"),
    ("channel_table.xlsx", "channel_table_2.xlsx"),
    ("network_table.xlsx", "network_table_2.xlsx"),
    ("community_table.xlsx", "community_table_2.xlsx"),
]


def _patch_compare_html(content: str) -> str:
    """Patch an HTML file from the compare project: rewrite internal links and inject DATA_DIR."""
    for old, new in _HTML_LINK_RENAMES:
        content = content.replace(old, new)
    injection = '<script>window.DATA_DIR = "data_2/";</script>\n'
    for marker in ('<script src="js/', '<script type="module" src="js/'):
        idx = content.find(marker)
        if idx != -1:
            content = content[:idx] + injection + content[idx:]
            break
    return content


def _patch_timeline_html(content: str, year: int) -> str:
    """Inject a DATA_DIR override for a per-year timeline export."""
    injection = f'<script>window.DATA_DIR = "data_{year}/";</script>\n'
    for marker in ('<script src="js/', '<script type="module" src="js/'):
        idx = content.find(marker)
        if idx != -1:
            content = content[:idx] + injection + content[idx:]
            break
    return content


def copy_compare_project(compare_dir: str, graph_dir: str) -> set[str]:
    """Copy files from a compare graph/ directory into graph/, renaming with _2 suffix.

    Returns the set of destination filenames that were actually written.
    """
    copied: set[str] = set()

    # data/ → data_2/
    src_data = os.path.join(compare_dir, "data")
    dst_data = os.path.join(graph_dir, "data_2")
    if os.path.exists(dst_data):
        shutil.rmtree(dst_data)
    if os.path.isdir(src_data):
        shutil.copytree(src_data, dst_data)
        copied.add("data_2")

    for src_name, dst_name in _COMPARE_RENAMES.items():
        src = os.path.join(compare_dir, src_name)
        if not os.path.isfile(src):
            continue
        dst = os.path.join(graph_dir, dst_name)
        if src_name.endswith(".html"):
            with open(src) as f:
                content = f.read()
            with open(dst, "w") as f:
                f.write(_patch_compare_html(content))
        else:
            shutil.copy2(src, dst)
        copied.add(dst_name)

    return copied


def write_timeline_json(timeline_entries: list[dict], graph_dir: str) -> None:
    data_dir = os.path.join(graph_dir, "data")
    os.makedirs(data_dir, exist_ok=True)
    # Strip private implementation keys (e.g. _xlsx_graph_data, _xlsx_community_data)
    # that are passed through timeline_entries for XLSX assembly but must not appear in JSON output.
    clean = [{k: v for k, v in e.items() if not k.startswith("_")} for e in timeline_entries]
    with open(os.path.join(data_dir, "timeline.json"), "w") as f:
        f.write(json.dumps({"years": clean}))


def write_network_compare_table_html(
    output_filename: str,
    seo: bool = False,
    project_title: str = "",
) -> None:
    title = f"{project_title} | Network comparison" if project_title else "Network comparison"
    robots_meta = "index, follow" if seo else "noindex, nofollow"

    context = {"title": title, "robots_meta": robots_meta}
    content = render_to_string("network/network_compare_table.html", context)
    with open(output_filename, "w") as f:
        f.write(content)


def write_community_table_xlsx(
    community_table_data: CommunityTableData,
    strategies: list[str],
    output_filename: str,
    project_title: str = "",
    year_data: "list[tuple[int, CommunityTableData]] | None" = None,
) -> None:
    headers = [
        "Community",
        "Color",
        "Nodes",
        "Internal Edges",
        "External Edges",
        "E-I Index",
        "Density",
        "Reciprocity",
        "Avg Clustering",
        "Avg Path Length",
        "Diameter",
        "Channels",
    ]

    def _fill_strategy(ws: Any, strategy_key: str, ctd: CommunityTableData, first: bool = True) -> None:
        strategy_entry = ctd["strategies"].get(strategy_key)
        if not strategy_entry:
            return
        if not first:
            ws.append([])  # blank separator between strategies
        heading_row = ws.max_row + 1
        ws.append([strategy_key.capitalize()])
        ws.cell(row=heading_row, column=1).font = Font(bold=True)
        ws.append(headers)
        for cell in ws[ws.max_row]:
            cell.font = Font(bold=True)
        for entry in strategy_entry["rows"]:
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
                    metrics.get("ei_index"),
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
            except (ValueError, TypeError):
                pass

    wb = openpyxl.Workbook()
    wb.properties.creator = "Pulpit"
    if project_title:
        wb.properties.title = project_title
    wb.remove(wb.active)

    if year_data:
        # One sheet per year; each sheet lists all strategies sequentially
        ws_all = wb.create_sheet(title="All")
        for i, sk in enumerate(strategies):
            _fill_strategy(ws_all, sk, community_table_data, first=(i == 0))
        for yr, yr_ctd in year_data:
            ws_yr = wb.create_sheet(title=str(yr))
            for i, sk in enumerate(strategies):
                _fill_strategy(ws_yr, sk, yr_ctd, first=(i == 0))
    else:
        # One sheet per strategy (original format)
        for strategy_key in strategies:
            ws = wb.create_sheet(title=strategy_key.capitalize()[:31])
            _fill_strategy(ws, strategy_key, community_table_data)

    wb.save(output_filename)


def write_community_metrics_json(
    community_table_data: CommunityTableData,
    strategies: list[str],
    graph_dir: str,
) -> None:
    data_dir = os.path.join(graph_dir, "data")
    communities_path = os.path.join(data_dir, "communities.json")
    with open(communities_path) as f:
        communities_file = json.load(f)

    for strategy_key in strategies:
        entry = community_table_data["strategies"].get(strategy_key)
        if not entry:
            continue
        rows_out = []
        for row in entry["rows"]:
            _community_id, _count, label, hex_color = row["group"]
            hex_color = str(hex_color)
            if not hex_color.startswith("#"):
                hex_color = f"#{hex_color}"
            rows_out.append(
                {
                    "label": str(label),
                    "hex_color": hex_color,
                    "node_count": row["node_count"],
                    "metrics": row["metrics"],
                    "channels": row.get("channels", []),
                }
            )
        strategy_entry = communities_file["strategies"].get(strategy_key)
        if strategy_entry is not None:
            strategy_entry["rows"] = rows_out
            mod = entry.get("modularity")
            strategy_entry["modularity"] = round(mod, 6) if mod is not None else None
            icr = entry.get("inter_community_edge_ratio")
            strategy_entry["inter_community_edge_ratio"] = round(icr, 6) if icr is not None else None
            mei = entry.get("mean_ei_index")
            strategy_entry["mean_ei_index"] = round(mei, 6) if mei is not None else None
            cross_tab = entry.get("org_cross_tab")
            if cross_tab is not None:
                strategy_entry["org_cross_tab"] = cross_tab

    with open(communities_path, "w") as f:
        f.write(json.dumps(communities_file))


def write_community_table_html(
    output_filename: str,
    seo: bool = False,
    project_title: str = "",
) -> None:
    if seo:
        title = f"{project_title} | Community statistics" if project_title else "Community statistics"
        robots_meta = "index, follow"
    else:
        title = f"{project_title} | Communities" if project_title else "Communities"
        robots_meta = "noindex, nofollow"

    context = {"title": title, "robots_meta": robots_meta}
    content = render_to_string("network/community_table.html", context)
    with open(output_filename, "w") as f:
        f.write(content)


def write_consensus_matrix_html(
    output_filename: str,
    seo: bool = False,
    project_title: str = "",
) -> None:
    title = f"{project_title} | Consensus matrix" if project_title else "Consensus matrix"
    robots_meta = "index, follow" if seo else "noindex, nofollow"

    context = {"title": title, "robots_meta": robots_meta}
    content = render_to_string("network/consensus_matrix.html", context)
    with open(output_filename, "w") as f:
        f.write(content)


def write_vacancy_analysis_html(
    output_filename: str,
    seo: bool = False,
    project_title: str = "",
) -> None:
    title = f"{project_title} | Vacancy Analysis" if project_title else "Vacancy Analysis"
    robots_meta = "index, follow" if seo else "noindex, nofollow"

    context = {"title": title, "robots_meta": robots_meta}
    content = render_to_string("network/vacancy_analysis.html", context)
    with open(output_filename, "w") as f:
        f.write(content)


def write_index_html(
    output_filename: str,
    seo: bool = False,
    project_title: str = "",
    include_graph: bool = False,
    include_3d_graph: bool = False,
    include_channel_html: bool = False,
    include_channel_xlsx: bool = False,
    include_network_html: bool = False,
    include_network_xlsx: bool = False,
    include_community_html: bool = False,
    include_community_xlsx: bool = False,
    include_consensus_matrix_html: bool = False,
    include_compare_html: bool = False,
    compare_files: set[str] | None = None,
    strategies: list[str] | None = None,
    timeline_entries: list[dict] | None = None,
    include_vacancy_analysis: bool = False,
) -> None:
    if seo:
        title = project_title or "Network Analysis"
        robots_meta = "index, follow"
    else:
        title = project_title or "Network Analysis"
        robots_meta = "noindex, nofollow"

    context = {
        "title": title,
        "robots_meta": robots_meta,
        "project_title": project_title,
        "include_graph": include_graph,
        "include_3d_graph": include_3d_graph,
        "include_channel_html": include_channel_html,
        "include_channel_xlsx": include_channel_xlsx,
        "include_network_html": include_network_html,
        "include_network_xlsx": include_network_xlsx,
        "include_community_html": include_community_html,
        "include_community_xlsx": include_community_xlsx,
        "include_consensus_matrix_html": include_consensus_matrix_html,
        "include_compare_html": include_compare_html,
        "compare_files": compare_files or set(),
        "strategies": [s.capitalize() for s in (strategies or [])],
        "timeline_entries": timeline_entries or [],
        "include_vacancy_analysis": include_vacancy_analysis,
    }
    content = render_to_string("network/index.html", context)
    with open(output_filename, "w") as f:
        f.write(content)
