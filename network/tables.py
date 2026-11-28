import datetime
import json
import os
import re
import shutil
from typing import TYPE_CHECKING, Any

from django.conf import settings
from django.template.loader import render_to_string

from network import label_mixing, mrqap, pages
from network.community import labelgroup_display_labels, strategy_display_label
from network.community_stats import PARTITION_COMPARISON_METRICS, SIGNIFICANCE_COLUMNS, network_summary_rows
from network.exporter import channel_table, community_value
from network.publication import robots_content
from network.utils import CommunityTableData, GraphData, int_id

import openpyxl
from openpyxl.styles import PatternFill

if TYPE_CHECKING:
    from network.audience_layer import AudienceExport

# Excel forbids \ / ? * : [ ] in sheet titles and caps them at 31 chars.
_SHEET_TITLE_INVALID = re.compile(r"[\\/?*:]")


def _safe_sheet_title(title: str, limit: int = 31, suffix: str = "") -> str:
    """Sanitise an arbitrary string into a valid Excel sheet title.

    Strategy display labels can contain characters Excel bans in sheet names —
    a label group's own name may hold ``[``/``]``, ``:`` or ``/``, all illegal
    there. Brackets read fine as parentheses; the other
    forbidden characters collapse to spaces. The result is whitespace-trimmed
    and truncated to Excel's 31-char cap (never empty), ``suffix`` (a continuation
    or duplicate mark) always kept whole.
    """
    cleaned = _SHEET_TITLE_INVALID.sub(" ", title).replace("[", "(").replace("]", ")")
    cleaned = " ".join(cleaned.split()).strip()
    return (cleaned or "Sheet")[: limit - len(suffix)].rstrip() + suffix


def _new_sheet(wb: Any, title: str, suffix: str = "") -> Any:
    """A new sheet titled *title*, made unique within the workbook: two label groups whose names share their
    first characters would otherwise truncate to one title, which openpyxl renames past Excel's limit."""
    name = _safe_sheet_title(title, suffix=suffix)
    taken = {existing.lower() for existing in wb.sheetnames}  # Excel compares sheet names case-insensitively
    n = 2
    while name.lower() in taken:
        name = _safe_sheet_title(title, suffix=f"{suffix} ~{n}")
        n += 1
    return wb.create_sheet(title=name)


def _pulpit_ctx() -> dict:
    # Display names for the manual LABELGROUP<id> partitions, injected into every table page as
    # window.STRATEGY_LABELS so labels.js → strategy_label() shows the analyst's group name ("Area")
    # instead of a title-cased key ("Labelgroup1"). Escape "</" so a group name containing "</script>"
    # can't break out of the inline <script> (mirrors network.exporter._patch_html_file).
    strategy_labels_json = json.dumps(labelgroup_display_labels()).replace("</", "<\\/")
    return {
        "repository_url": getattr(settings, "REPOSITORY_URL", ""),
        "app_version": getattr(settings, "APP_VERSION", ""),
        "strategy_labels_json": strategy_labels_json,
    }


def page_context(
    page_file: str,
    project_title: str,
    *,
    title: str = "",
    description: str = "",
    generated: str = "",
    app_version: str = "",
) -> dict:
    """The context every export page's frame (``_table_base.html``) reads, from the page catalogue.

    *title* / *description* override the catalogue's (the landing page, the methods and data pages).
    The browser-tab title reads ``"<project> | <page>"``, the page's own heading the page title alone.
    *generated* / *app_version*: the export's own date and version, for the pages the site pass renders again
    later (``compare_analysis``); a page written during the run takes today's and the running version's.
    """
    found = pages.lookup(page_file)
    page_title = title or pages.page_title(page_file)
    version = app_version or getattr(settings, "APP_VERSION", "")
    question = ""
    doc_url = ""
    if found is not None:
        found_card, _entry, _compared = found
        question = found_card.question
        doc_url = pages.docs_url(getattr(settings, "REPOSITORY_URL", ""), version, found_card.doc)
    return {
        "title": " | ".join(part for part in (project_title, page_title) if part) or "Network analysis",
        "description": description or pages.page_description(page_file),
        "project_title": project_title,
        "generated": generated or datetime.date.today().isoformat(),
        "page": {"file": page_file, "title": page_title, "question": question, "doc_url": doc_url},
        **_pulpit_ctx(),
        "app_version": version,
    }


def _write_page(
    template: str,
    output_filename: str,
    *,
    seo: bool,
    project_title: str,
    description: str = "",
    extra: dict | None = None,
) -> None:
    """Render an export page: its title, lede and method link come from the page catalogue (``network.pages``),
    by the file name it is written to. ``description`` overrides the catalogue's (the channel table counts its
    channels); ``extra`` adds to the template context.
    """
    context = {
        **page_context(os.path.basename(output_filename), project_title, description=description),
        # Provisional: publication.publish() sets every page's policy tags once the export is complete.
        "robots_meta": robots_content(seo),
        **(extra or {}),
    }
    content = render_to_string(template, context)
    with open(output_filename, "w", encoding="utf-8") as f:
        f.write(content)


def write_table_html(
    graph_data: GraphData,
    output_filename: str,
    seo: bool = False,
    project_title: str = "",
) -> None:
    n = len(graph_data["nodes"])
    _write_page(
        "network/channel_table.html",
        output_filename,
        seo=seo,
        project_title=project_title,
        description=(
            f"Network data for {n} Telegram channels, "
            "including activity metrics, inbound and outbound tie strength, and community assignments."
        ),
    )


def _new_workbook(project_title: str) -> Any:
    """An empty workbook (no sheet) with Pulpit's document properties."""
    wb = openpyxl.Workbook()
    wb.properties.creator = "Pulpit"
    if project_title:
        wb.properties.title = project_title
    wb.remove(wb.active)
    return wb


def _table_sheet(wb: Any, title: str, headers: list[str], scopes: list[tuple[str, list[list[Any]]]]) -> Any:
    """One table on one sheet. ``scopes`` are ``(period, rows)``: with a timeline (more than one scope) the table
    gains a leading ``Period`` column, "All periods" for the full range, so every period sits in the same table.

    Styling, widths, number formats and the About sheet are added once the export is complete
    (``network.workbooks.finish``).
    """
    with_period = len(scopes) > 1
    header = ([pages.PERIOD_HEADER] if with_period else []) + list(headers)
    ws = _new_sheet(wb, title)
    ws.append(header)
    part = 1
    for period, rows in scopes:
        for row in rows:
            if ws.max_row >= EXCEL_MAX_ROWS:
                # A sheet cannot hold more: the table goes on in "<title> (2)", "<title> (3)"…, same header.
                part += 1
                ws = _new_sheet(wb, title, suffix=f" ({part})")
                ws.append(header)
            _append_row(ws, ([period] if with_period else []) + list(row))
    return ws


# Limits of the XLSX format (Excel's, which every reader of the format shares).
EXCEL_MAX_ROWS = 1_048_576
EXCEL_MAX_CELL_CHARS = 32_767
_TRUNCATED = " […]"


def _append_row(ws: Any, values: list[Any]) -> None:
    """Append a data row as the workbooks hold values: yes/no as 1/0 (as in the CSVs), text never read as a
    formula (a channel's title may open with "="), and no text beyond what a cell can hold."""
    cleaned: list[Any] = []
    formulas: list[int] = []
    for index, value in enumerate(values, start=1):
        if isinstance(value, bool):
            value = int(value)
        elif isinstance(value, str):
            if len(value) > EXCEL_MAX_CELL_CHARS:
                value = value[: EXCEL_MAX_CELL_CHARS - len(_TRUNCATED)] + _TRUNCATED
            if value.startswith("="):
                formulas.append(index)
        cleaned.append(value)
    ws.append(cleaned)
    for index in formulas:
        ws.cell(row=ws.max_row, column=index).data_type = "s"


def _scopes(full: Any, year_data: "list[tuple[Any, Any]] | None") -> list[tuple[str, Any]]:
    """The full range, then each timeline period, as ``(period label, payload)``."""
    return [(pages.ALL_PERIODS, full)] + [(str(period), payload) for period, payload in year_data or []]


def write_table_xlsx(
    graph_data: GraphData,
    measures_labels: list[tuple[str, str]],
    strategies: list[str],
    output_filename: str,
    project_title: str = "",
    year_data: "list[tuple[int, GraphData]] | None" = None,
) -> None:
    """channel_table.xlsx: the channel table (``exporter.channel_table``), every period in one sheet."""
    headers, _rows = channel_table(graph_data, measures_labels, strategies)
    headers = list(headers)
    tables_by_period = [
        (period, channel_table(gd, measures_labels, strategies)) for period, gd in _scopes(graph_data, year_data)
    ]
    # A period's table has the columns its own channels carry (an SBM confidence column exists only where a
    # channel holds the value), so its rows are placed under the shared headers by name, never by position.
    for _period, (period_headers, _period_rows) in tables_by_period:
        headers += [name for name in period_headers if name not in headers]
    scopes = []
    for period, (period_headers, period_rows) in tables_by_period:
        position = {name: i for i, name in enumerate(period_headers)}
        scopes.append(
            (period, [[row[position[name]] if name in position else None for name in headers] for row in period_rows])
        )
    wb = _new_workbook(project_title)
    _table_sheet(wb, "Channels", headers, scopes)
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
    tested_columns: set[str] = set()
    for label, value, group, significance in network_summary_rows(summary):
        if isinstance(value, float):
            display = _fmt(value)
        elif value is None:
            display = "—"
        elif isinstance(value, int) and not isinstance(value, bool):
            display = f"{value:,}"
        else:
            display = str(value)
        summary_rows.append({"label": label, "value": display, "group": group, "significance": significance})
        tested_columns.update(significance or ())

    modularity_rows = []
    for strategy_key in strategies:
        entry = community_table_data["strategies"].get(strategy_key)
        mod = entry["modularity"] if entry else None
        icr = entry.get("inter_community_edge_ratio") if entry else None
        mei = entry.get("mean_ei_index") if entry else None
        mod_z = entry.get("modularity_z") if entry else None
        mod_p = entry.get("modularity_p") if entry else None
        modularity_rows.append(
            {
                "strategy": strategy_key,
                "modularity": _fmt(mod) if mod is not None else "—",
                "modularity_z": _fmt(mod_z, 1) if mod_z is not None else "—",
                "modularity_p": _fmt(mod_p, 3) if mod_p is not None else "—",
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
        # Baselines at least one row is tested against, in column order (network table "vs …" columns).
        "significance_columns": [[key, label] for key, label in SIGNIFICANCE_COLUMNS if key in tested_columns],
        "modularity_rows": modularity_rows,
        "partition_comparison": community_table_data.get("partition_comparison"),
        "label_mixing": community_table_data.get("label_mixing"),
        "mrqap": community_table_data.get("mrqap"),
    }
    with open(os.path.join(data_dir, "network_metrics.json"), "w") as f:
        f.write(json.dumps(payload))


def write_network_table_html(
    output_filename: str,
    seo: bool = False,
    project_title: str = "",
) -> None:
    _write_page(
        "network/network_table.html",
        output_filename,
        seo=seo,
        project_title=project_title,
    )


def write_network_table_xlsx(
    community_table_data: CommunityTableData,
    strategies: list[str],
    output_filename: str,
    project_title: str = "",
    year_data: "list[tuple[int, CommunityTableData]] | None" = None,
) -> None:
    """network_table.xlsx: one table per sheet (statistics, modularity, partition comparison, homophily, label flows,
    the dyadic regression), every period of a timeline in the same table."""
    periods = _scopes(community_table_data, year_data)
    wb = _new_workbook(project_title)

    # Whole-network statistics, with a z and a p per baseline any statistic of any period was tested against.
    tested = {
        key
        for _period, ctd in periods
        for *_rest, significance in network_summary_rows(ctd["network_summary"])
        for key in (significance or ())
    }
    columns = [(key, label) for key, label in SIGNIFICANCE_COLUMNS if key in tested]

    def _statistic_rows(ctd: CommunityTableData) -> list[list[Any]]:
        rows = []
        for label, value, group, significance in network_summary_rows(ctd["network_summary"]):
            cells: list[Any] = []
            for key, _label in columns:
                test = (significance or {}).get(key)
                if test is None:
                    cells += [None, None]
                elif test.get("fixed"):
                    cells += ["held fixed", None]
                else:
                    cells += [test.get("z"), test.get("p")]
            rows.append([group, label, value, *cells])
        return rows

    _table_sheet(
        wb,
        "Statistics",
        ["Group", "Statistic", "Value", *(f"{part} {label}" for _key, label in columns for part in ("z", "p"))],
        [(period, _statistic_rows(ctd)) for period, ctd in periods],
    )

    def _modularity_rows(ctd: CommunityTableData) -> list[list[Any]]:
        rows = []
        for strategy_key in strategies:
            entry = ctd["strategies"].get(strategy_key) or {}
            rows.append(
                [
                    strategy_display_label(strategy_key),
                    entry.get("modularity"),
                    entry.get("modularity_z"),
                    entry.get("modularity_p"),
                    entry.get("inter_community_edge_ratio"),
                    entry.get("mean_ei_index"),
                ]
            )
        return rows

    _table_sheet(
        wb,
        "Modularity",
        ["Method", "Modularity", "Modularity z", "p (vs random graphs)", "Inter-community ratio", "Mean E-I index"],
        [(period, _modularity_rows(ctd)) for period, ctd in periods],
    )

    def _comparison_rows(ctd: CommunityTableData) -> list[list[Any]]:
        comparison = ctd.get("partition_comparison")
        if not comparison or len(comparison.get("strategies", [])) < 2:
            return []
        labels = [strategy_display_label(s) for s in comparison["strategies"]]
        rows = []
        for metric_key, abbr, name, _is_distance in PARTITION_COMPARISON_METRICS:
            cells = comparison["metrics"].get(metric_key)
            if not cells:
                continue
            for i, label_a in enumerate(labels):
                for j, label_b in enumerate(labels):
                    if i != j:
                        rows.append([f"{name} ({abbr})", label_a, label_b, cells[i][j]])
        return rows

    comparison_scopes = [(period, _comparison_rows(ctd)) for period, ctd in periods]
    if any(rows for _period, rows in comparison_scopes):
        _table_sheet(wb, "Partition comparison", ["Index", "Method A", "Method B", "Value"], comparison_scopes)

    # Homophily, label flows and MRQAP rows already carry their period in their first column.
    mixing = [(period, ctd["label_mixing"]) for period, ctd in periods if ctd.get("label_mixing")]
    if any(payload.get("groups") for _period, payload in mixing):
        for title, cols, rows_of in (
            ("Homophily", label_mixing.GROUP_COLUMNS, label_mixing.group_rows),
            ("Homophily by label", label_mixing.LABEL_COLUMNS, label_mixing.label_rows),
            ("Label flows", label_mixing.FLOW_COLUMNS, label_mixing.flow_rows),
        ):
            _table_sheet(wb, title, list(cols), [("", [r for p, payload in mixing for r in rows_of(payload, p)])])

    regressions = [(period, ctd["mrqap"]) for period, ctd in periods if ctd.get("mrqap")]
    if any(payload.get("models") for _period, payload in regressions):
        for title, cols, rows_of in (
            ("MRQAP models", mrqap.MODEL_COLUMNS, mrqap.model_rows),
            ("MRQAP coefficients", mrqap.COEFFICIENT_COLUMNS, mrqap.coefficient_rows),
        ):
            _table_sheet(wb, title, list(cols), [("", [r for p, payload in regressions for r in rows_of(payload, p)])])

    wb.save(output_filename)


# Files of the compared analysis copied in as ``<name>_2.<ext>`` (network.pages.compared_name).
_COMPARED_FILES: tuple[str, ...] = (
    "graph.html",
    "graph3d.html",
    "channel_table.html",
    "network_table.html",
    "community_table.html",
    "consensus_matrix.html",
    "structural_equivalence.html",
    "behavioural_equivalence.html",
    "channel_table.xlsx",
    "network_table.xlsx",
    "community_table.xlsx",
)
_COMPARE_RENAMES: dict[str, str] = {name: pages.compared_name(name) for name in _COMPARED_FILES}

# Every page link a copied page may hold, longest first so that graph3d.html is replaced before graph.html.
_HTML_LINK_RENAMES: list[tuple[str, str]] = sorted(
    [(name, pages.compared_name(name)) for name in _COMPARED_FILES], key=lambda pair: -len(pair[0])
)
COMPARED_TITLE_SUFFIX = " (compared analysis)"
_TITLE_RE = re.compile(r"(<title>)(.*?)(</title>)", re.S)
_H1_RE = re.compile(r'(<h1 class="export-title">)(.*?)(</h1>)', re.S)


def _patch_compare_html(content: str) -> str:
    """Patch a page copied from the compared analysis: its links point at the other copies, it reads its data
    from ``data_2/``, and its browser title and heading say which analysis it shows."""
    for old, new in _HTML_LINK_RENAMES:
        content = content.replace(old, new)

    def retitle(match: re.Match) -> str:
        text = match.group(2)
        return (
            match.group(1)
            + (text if text.endswith(COMPARED_TITLE_SUFFIX) else text + COMPARED_TITLE_SUFFIX)
            + match.group(3)
        )

    content = _TITLE_RE.sub(retitle, content, count=1)
    content = _H1_RE.sub(retitle, content, count=1)
    injection = '<script>window.DATA_DIR = "data_2/";</script>\n'
    for marker in ('<script src="js/', '<script type="module" src="js/'):
        idx = content.find(marker)
        if idx != -1:
            content = content[:idx] + injection + content[idx:]
            break
    return content


def copy_compare_project(compare_dir: str, graph_dir: str) -> set[str]:
    """Copy the compared analysis' pages, workbooks and data from *compare_dir* into *graph_dir* as ``*_2``.

    Copies left by an earlier comparison are removed first, so a page the new compared analysis does not have
    is never offered as its own. The analysis' ``summary.json`` travels into ``data_2/`` with its data: the
    site pass reads it for what a compared workbook's About sheet states. Returns the names written.
    """
    copied: set[str] = set()
    for dst_name in _COMPARE_RENAMES.values():
        stale = os.path.join(graph_dir, dst_name)
        if os.path.isfile(stale):
            os.remove(stale)

    # data/ → data_2/
    src_data = os.path.join(compare_dir, "data")
    dst_data = os.path.join(graph_dir, "data_2")
    if os.path.exists(dst_data):
        shutil.rmtree(dst_data)
    if os.path.isdir(src_data):
        shutil.copytree(src_data, dst_data)
        copied.add("data_2")
        src_summary = os.path.join(compare_dir, "summary.json")
        if os.path.isfile(src_summary):
            shutil.copy2(src_summary, os.path.join(dst_data, "summary.json"))

    for src_name, dst_name in _COMPARE_RENAMES.items():
        src = os.path.join(compare_dir, src_name)
        if not os.path.isfile(src):
            continue
        dst = os.path.join(graph_dir, dst_name)
        if src_name.endswith(".html"):
            with open(src, encoding="utf-8") as f:
                content = f.read()
            with open(dst, "w", encoding="utf-8") as f:
                f.write(_patch_compare_html(content))
        else:
            shutil.copy2(src, dst)
        copied.add(dst_name)

    return copied


def write_timeline_json(
    timeline_entries: list[dict],
    graph_dir: str,
    *,
    step: str = "year",
    window_months: int | None = None,
    overlapping: bool = False,
    events: list[dict] | None = None,
) -> None:
    """Write ``data/timeline.json``: ``{"step", "window_months", "overlapping", "periods", "events"}``.

    ``periods`` lists the exported periods in timeline order, each with ``key`` (its ``data_<key>/``
    directory), ``label``, ``start`` / ``end`` and the per-period flags the viewers read; ``events`` the
    analyst's events inside the timeline, each with the ``period_key`` of the step containing it.
    """
    data_dir = os.path.join(graph_dir, "data")
    os.makedirs(data_dir, exist_ok=True)
    # Strip private implementation keys (e.g. _xlsx_graph_data, _xlsx_community_data)
    # that are passed through timeline_entries for XLSX assembly but must not appear in JSON output.
    clean = [{k: v for k, v in e.items() if not k.startswith("_")} for e in timeline_entries]
    payload = {
        "step": step,
        "window_months": window_months,
        "overlapping": overlapping,
        "periods": clean,
        "events": events or [],
    }
    with open(os.path.join(data_dir, "timeline.json"), "w") as f:
        f.write(json.dumps(payload))


def write_network_compare_table_html(
    output_filename: str,
    seo: bool = False,
    project_title: str = "",
) -> None:
    _write_page(
        "network/network_compare_table.html",
        output_filename,
        seo=seo,
        project_title=project_title,
    )


def write_community_table_xlsx(
    community_table_data: CommunityTableData,
    strategies: list[str],
    output_filename: str,
    project_title: str = "",
    year_data: "list[tuple[int, CommunityTableData]] | None" = None,
) -> None:
    """community_table.xlsx: one row per community of every grouping method (and period), in one sheet."""
    headers = [
        "Method",
        "Community",
        "Colour",
        "Channels",
        "Internal ties",
        "External ties",
        "E-I index",
        "Internal density",
        "Reciprocity",
        "Mean clustering",
        "Mean path length",
        "Diameter",
        "Modularity contribution",
        "Members",
    ]

    def _rows(ctd: CommunityTableData) -> list[list[Any]]:
        rows = []
        for strategy_key in strategies:
            strategy_entry = ctd["strategies"].get(strategy_key)
            if not strategy_entry:
                continue
            for entry in strategy_entry["rows"]:
                _community_id, _count, label, hex_color = entry["group"]
                metrics = entry["metrics"]
                rows.append(
                    [
                        strategy_display_label(strategy_key),
                        community_value(label, strategy_key),
                        f"#{str(hex_color).lstrip('#')}",
                        entry["node_count"],
                        metrics["internal_edges"],
                        metrics["external_edges"],
                        metrics.get("ei_index"),
                        metrics["density"],
                        metrics["reciprocity"],
                        metrics["avg_clustering"],
                        metrics["avg_path_length"],
                        metrics["diameter"],
                        metrics.get("modularity_contribution"),
                        ", ".join(c["label"] for c in entry.get("channels", [])),
                    ]
                )
        return rows

    wb = _new_workbook(project_title)
    ws = _table_sheet(
        wb, "Communities", headers, [(p, _rows(ctd)) for p, ctd in _scopes(community_table_data, year_data)]
    )
    # The Colour cell shows the community's colour on the map.
    colour_col = list(next(ws.iter_rows(min_row=1, max_row=1, values_only=True))).index("Colour") + 1
    for (cell,) in ws.iter_rows(min_row=2, min_col=colour_col, max_col=colour_col):
        hex_color = str(cell.value or "").lstrip("#").upper()
        if re.fullmatch(r"[0-9A-F]{6}", hex_color):
            cell.fill = PatternFill(start_color=hex_color, end_color=hex_color, fill_type="solid")
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
            strategy_entry["modularity_z"] = entry.get("modularity_z")
            strategy_entry["modularity_p"] = entry.get("modularity_p")
            icr = entry.get("inter_community_edge_ratio")
            strategy_entry["inter_community_edge_ratio"] = round(icr, 6) if icr is not None else None
            mei = entry.get("mean_ei_index")
            strategy_entry["mean_ei_index"] = round(mei, 6) if mei is not None else None
            cross_tabs = entry.get("cross_tabs")
            if cross_tabs is not None:
                strategy_entry["cross_tabs"] = cross_tabs

    with open(communities_path, "w") as f:
        f.write(json.dumps(communities_file))


def write_community_table_html(
    output_filename: str,
    seo: bool = False,
    project_title: str = "",
) -> None:
    _write_page(
        "network/community_table.html",
        output_filename,
        seo=seo,
        project_title=project_title,
    )


def write_consensus_matrix_html(
    output_filename: str,
    seo: bool = False,
    project_title: str = "",
) -> None:
    _write_page(
        "network/consensus_matrix.html",
        output_filename,
        seo=seo,
        project_title=project_title,
    )


def write_structural_equivalence_json(sim_data: dict, graph_dir: str) -> None:
    # The page shows structural equivalence (Lorrain & White 1971); file and page are named after it.
    data_dir = os.path.join(graph_dir, "data")
    os.makedirs(data_dir, exist_ok=True)
    with open(os.path.join(data_dir, "structural_equivalence.json"), "w") as f:
        f.write(json.dumps(sim_data))


def write_structural_equivalence_html(
    output_filename: str,
    seo: bool = False,
    project_title: str = "",
) -> None:
    _write_page(
        "network/structural_equivalence.html",
        output_filename,
        seo=seo,
        project_title=project_title,
    )


def write_behavioural_equivalence_json(sim_data: dict, graph_dir: str) -> None:
    data_dir = os.path.join(graph_dir, "data")
    os.makedirs(data_dir, exist_ok=True)
    with open(os.path.join(data_dir, "behavioural_equivalence.json"), "w") as f:
        f.write(json.dumps(sim_data))


def write_behavioural_equivalence_html(
    output_filename: str,
    seo: bool = False,
    project_title: str = "",
) -> None:
    _write_page(
        "network/behavioural_equivalence.html",
        output_filename,
        seo=seo,
        project_title=project_title,
    )


def write_vacancy_analysis_html(
    output_filename: str,
    seo: bool = False,
    project_title: str = "",
) -> None:
    _write_page(
        "network/vacancy_analysis.html",
        output_filename,
        seo=seo,
        project_title=project_title,
    )


def write_robustness_table_html(
    output_filename: str,
    seo: bool = False,
    project_title: str = "",
) -> None:
    _write_page(
        "network/robustness_table.html",
        output_filename,
        seo=seo,
        project_title=project_title,
    )


def write_interesting_messages_html(
    output_filename: str,
    seo: bool = False,
    project_title: str = "",
) -> None:
    _write_page(
        "network/interesting_messages.html",
        output_filename,
        seo=seo,
        project_title=project_title,
    )


_ROBUSTNESS_METRICS: tuple[str, ...] = ("wcc", "scc", "reach", "strength")


_ROBUSTNESS_MEASURE_LABELS = {"wcc": "WCC", "scc": "SCC", "reach": "Reach", "strength": "Strength"}


def _robustness_strategy(payload: dict, key: str) -> str:
    return (payload.get("strategies", {}).get(key) or {}).get("label") or key


def _share_removed(i: int, n: int) -> float:
    return i / (n - 1) if n > 1 else 0.0


def _robustness_summary_rows(payload: dict) -> list[list[Any]]:
    rows = []
    for s, strat in payload.get("strategies", {}).items():
        null = strat.get("null") or {}
        for m in _ROBUSTNESS_METRICS:
            null_m = null.get(f"r_{m}") or {}
            rows.append(
                [
                    _robustness_strategy(payload, s),
                    _ROBUSTNESS_MEASURE_LABELS[m],
                    strat.get(f"r_{m}"),
                    null_m.get("mean"),
                    null_m.get("std"),
                    null_m.get("z"),
                    null_m.get("p"),
                    null_m.get("q"),
                    strat.get(f"fc_{m}"),
                ]
            )
    return rows


def _robustness_curve_rows(payload: dict) -> list[list[Any]]:
    rows = []
    for s, strat in payload.get("strategies", {}).items():
        null = strat.get("null") or {}
        for m in _ROBUSTNESS_METRICS:
            curve = strat.get(f"curve_{m}") or []
            mean, std = null.get(f"curve_{m}_mean") or [], null.get(f"curve_{m}_std") or []
            for i, value in enumerate(curve):
                rows.append(
                    [
                        _robustness_strategy(payload, s),
                        _ROBUSTNESS_MEASURE_LABELS[m],
                        _share_removed(i, len(curve)),
                        value,
                        mean[i] if i < len(mean) else None,
                        std[i] if i < len(std) else None,
                    ]
                )
    return rows


def _robustness_efficiency_rows(payload: dict) -> list[list[Any]]:
    eff = payload.get("efficiency") or {}
    curves, fractions = eff.get("curves") or {}, eff.get("fractions") or []
    return [
        [_robustness_strategy(payload, s), f, curves[s][i] if i < len(curves[s]) else None]
        for s in payload.get("strategies", {})
        if s in curves
        for i, f in enumerate(fractions)
    ]


def _robustness_ban_wave_rows(payload: dict) -> list[list[Any]]:
    rows = []
    for partition, partition_rows in (payload.get("ban_waves") or {}).items():
        for row in partition_rows:
            for m in _ROBUSTNESS_METRICS:
                rows.append(
                    [
                        strategy_display_label(partition),
                        # A label for a label group, the community's number for an algorithmic method.
                        row.get("community_label") or int_id(row.get("community")),
                        row.get("n"),
                        row.get("fraction"),
                        _ROBUSTNESS_MEASURE_LABELS[m],
                        row.get(f"s_{m}"),
                        row.get(f"random_{m}"),
                    ]
                )
    return rows


def _robustness_modular_rows(payload: dict) -> list[list[Any]]:
    rows = []
    for partition, per_strategy in (payload.get("modular") or {}).items():
        for s, curves in per_strategy.items():
            n = len(curves.get("intra") or [])
            for i in range(n):
                rows.append(
                    [
                        strategy_display_label(partition),
                        _robustness_strategy(payload, s),
                        _share_removed(i, n),
                        curves["intra"][i],
                        curves["inter"][i] if i < len(curves.get("inter") or []) else None,
                        curves["ratio"][i] if i < len(curves.get("ratio") or []) else None,
                    ]
                )
    return rows


def write_robustness_table_xlsx(
    rob_payload: dict,
    output_filename: str,
    project_title: str = "",
    year_data: "list[tuple[int, dict]] | None" = None,
) -> None:
    """robustness_table.xlsx: one table per sheet (summary, curves, efficiency, ban waves, modular robustness, and for
    the full range the ban replay and the α sensitivity), every period of a timeline in the same table."""
    periods = _scopes(rob_payload, year_data)
    wb = _new_workbook(project_title)
    for title, headers, rows_of in (
        (
            "Summary",
            ["Strategy", "Measure", "R", "Random R, mean", "Random R, SD", "z", "p", "q", "Critical share"],
            _robustness_summary_rows,
        ),
        (
            "Curves",
            ["Strategy", "Measure", "Share removed", "Residual size", "Random, mean", "Random, SD"],
            _robustness_curve_rows,
        ),
        ("Efficiency", ["Strategy", "Share removed", "Efficiency"], _robustness_efficiency_rows),
        (
            "Ban waves",
            [
                "Method",
                "Community",
                "Channels",
                "Share of the network",
                "Measure",
                "Residual size",
                "Random residual",
            ],
            _robustness_ban_wave_rows,
        ),
        (
            "Modular",
            ["Method", "Strategy", "Share removed", "Within communities", "Between communities", "Ratio"],
            _robustness_modular_rows,
        ),
    ):
        scopes = [(period, rows_of(payload)) for period, payload in periods]
        if any(rows for _period, rows in scopes):
            _table_sheet(wb, title, headers, scopes)

    replay = [
        [
            row.get("label") or row.get("period"),
            row.get("n_pre"),
            row.get("n_closed"),
            row.get("fraction"),
            _ROBUSTNESS_MEASURE_LABELS[m],
            row.get(f"predicted_{m}"),
            row.get(f"random_{m}"),
            row.get(f"observed_{m}"),
        ]
        for row in rob_payload.get("ban_replay") or []
        for m in _ROBUSTNESS_METRICS
    ]
    if replay:
        _table_sheet(
            wb,
            "Ban replay",
            [
                "Wave period",
                "Channels before",
                "Closed",
                "Share of the network",
                "Measure",
                "Predicted",
                "Random",
                "Observed",
            ],
            [("", replay)],
        )
    sens = rob_payload.get("alpha_sensitivity") or {}
    alpha_rows = [
        [
            row.get("alpha"),
            row.get("backbone_n"),
            row.get("backbone_m"),
            _ROBUSTNESS_MEASURE_LABELS[m],
            _robustness_strategy(rob_payload, s),
            ((row.get("r") or {}).get(s) or {}).get(m),
        ]
        for row in sens.get("rows") or []
        for m in _ROBUSTNESS_METRICS
        for s in sens.get("strategies", [])
        if s in rob_payload.get("strategies", {})
    ]
    if alpha_rows:
        _table_sheet(
            wb,
            "Alpha sensitivity",
            ["Alpha", "Backbone channels", "Backbone ties", "Measure", "Strategy", "R"],
            [("", alpha_rows)],
        )
    wb.save(output_filename)


def write_event_impact_html(output_filename: str, seo: bool = False, project_title: str = "") -> None:
    _write_page(
        "network/event_impact.html",
        output_filename,
        seo=seo,
        project_title=project_title,
    )


def write_event_impact_xlsx(payload: dict, output_filename: str, project_title: str = "") -> None:
    """``Effects`` (one row per event × metric) and ``Weekly series`` (the network's weekly metrics) sheets."""
    from network.event_impact import EFFECT_COLUMNS, effect_rows, series_rows

    wb = _new_workbook(project_title)
    _table_sheet(wb, "Effects", list(EFFECT_COLUMNS), [("", effect_rows(payload))])
    header, rows = series_rows(payload)
    _table_sheet(wb, "Weekly series", header, [("", rows)])
    wb.save(output_filename)


def write_links_html(output_filename: str, seo: bool = False, project_title: str = "") -> None:
    _write_page(
        "network/links.html",
        output_filename,
        seo=seo,
        project_title=project_title,
    )


def write_links_xlsx(
    payload: dict,
    output_filename: str,
    project_title: str = "",
    year_data: "list[tuple[str, dict]] | None" = None,
) -> None:
    """The outbound-link layer as a workbook: ``Channels``, ``Sites`` (every period of a timeline in the same table),
    ``Categories``, ``Co-linking``, ``Channel sites`` and one ``Matrix <group>`` sheet per partition label group."""
    from network.link_layer import (
        CATEGORY_COLUMNS,
        CHANNEL_COLUMNS,
        CHANNEL_SITE_COLUMNS,
        PAIR_COLUMNS,
        SITE_COLUMNS,
        channel_site_rows,
        flat_rows,
    )

    wb = _new_workbook(project_title)
    periods = _scopes(payload, year_data)
    for title, columns, key in (("Channels", CHANNEL_COLUMNS, "channels"), ("Sites", SITE_COLUMNS, "sites")):
        headers = [name for name, _ in columns]
        _table_sheet(wb, title, headers, [(p, flat_rows(columns, scope.get(key, []))[1]) for p, scope in periods])
    _table_sheet(wb, "Categories", *_single(flat_rows(CATEGORY_COLUMNS, payload.get("categories", []))))
    _table_sheet(wb, "Co-linking", *_single(flat_rows(PAIR_COLUMNS, payload.get("colinking", {}).get("pairs", []))))
    _table_sheet(wb, "Channel sites", list(CHANNEL_SITE_COLUMNS), [("", channel_site_rows(payload))])
    for matrix in payload.get("matrices", []):
        _table_sheet(
            wb,
            f"Matrix {matrix['group']}",
            [matrix["group"], *matrix["categories"], "Total"],
            [
                (
                    "",
                    [
                        [label, *counts, sum(counts)]
                        for label, counts in zip(matrix["labels"], matrix["counts"], strict=True)
                    ],
                )
            ],
        )
    wb.save(output_filename)


def _single(table: tuple[list[str], list[list[Any]]]) -> tuple[list[str], list[tuple[str, list[list[Any]]]]]:
    """``(headers, rows)`` as the ``(headers, scopes)`` of a table with no period."""
    headers, rows = table
    return headers, [("", rows)]


def write_audience_html(output_filename: str, seo: bool = False, project_title: str = "") -> None:
    _write_page(
        "network/audience.html",
        output_filename,
        seo=seo,
        project_title=project_title,
    )


def write_audience_xlsx(
    result: "AudienceExport",
    output_filename: str,
    project_title: str = "",
    year_data: "list[tuple[str, AudienceExport]] | None" = None,
) -> None:
    """The Audience sections as a workbook: a ``Summary`` sheet, each section's main table and the tables the page
    shows beside them; with *year_data* ``[(period key, result), …]`` the summary, participation and overlap pairs
    carry a Period column (:func:`network.audience_layer.xlsx_sheets`)."""
    from network.audience_layer import xlsx_sheets

    wb = _new_workbook(project_title)
    for title, headers, rows in xlsx_sheets(result, year_data):
        _table_sheet(wb, title, headers, [("", rows)])
    wb.save(output_filename)


def write_dominance_html(output_filename: str, seo: bool = False, project_title: str = "") -> None:
    _write_page(
        "network/dominance.html",
        output_filename,
        seo=seo,
        project_title=project_title,
    )


_HIERARCHY_LABELS = {
    "total_events": "Citation events",
    "links": "Directed links",
    "tested_links": "Links tested",
    "validated_links": "Links validated",
    "pairs": "Connected pairs",
    "share_basis": "Share basis",
}


def _hierarchy_rows(payload: dict) -> list[list[Any]]:
    """The whole-network hierarchy tests and the counts of a dominance payload, as readable ``Statistic, Value`` rows."""
    meta = payload.get("meta") or {}
    rows = [[_readable_key(key), value] for key, value in (meta.get("hierarchy") or {}).items()]
    rows += [[_HIERARCHY_LABELS[key], meta.get(key)] for key in _HIERARCHY_LABELS]
    for group, title in (("relations", "Pairs"), ("roles", "Channels")):
        rows += [[f"{title}: {key}", value] for key, value in (meta.get(group) or {}).items()]
    return rows


def _readable_key(key: str) -> str:
    """``springrank_energy`` → ``SpringRank energy``: a payload key as a spreadsheet label."""
    text = str(key).replace("_", " ").replace("springrank", "SpringRank").replace("null mean", "random mean")
    return text[:1].upper() + text[1:]


def write_dominance_xlsx(
    payload: dict,
    output_filename: str,
    project_title: str = "",
    year_data: "list[tuple[int, dict]] | None" = None,
) -> None:
    """The dominance analysis as a workbook: ``Channels`` (the ranked channels), ``Pairs`` and ``Hierarchy`` (the
    whole-network tests), every period of a timeline in the same table."""
    from network.dominance import flat_node_rows, flat_pair_rows

    periods = _scopes(payload, year_data)
    wb = _new_workbook(project_title)
    for title, flat in (("Channels", flat_node_rows), ("Pairs", flat_pair_rows)):
        headers = flat(payload)[0]
        _table_sheet(wb, title, headers, [(p, flat(scope)[1]) for p, scope in periods])
    _table_sheet(wb, "Hierarchy", ["Statistic", "Value"], [(p, _hierarchy_rows(scope)) for p, scope in periods])
    wb.save(output_filename)
