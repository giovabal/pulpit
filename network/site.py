"""The export as one small web site, assembled once all of its files are written.

:func:`finalise` runs last in ``structural_analysis`` (after ``summary.json``) and again in ``compare_analysis``.
It reads what is actually on disk, so no link points at a page or a file the export does not hold:

* ``methods.html``: ``PARAMETERS.md`` as a page;
* ``data.html`` and ``DATA.md``: the data dictionary (``network.data_dictionary``);
* ``index.html``: the study header, the cards grouped by research question (``network.pages``), the
  timeline's periods, the *Data and methods* file list and *How to cite*;
* in every page: the navigation (a breadcrumb and the *Contents* menu, the current page marked) between the
  ``<!-- pulpit:sitenav -->`` markers, and the page's method link and downloads between the
  ``<!-- pulpit:pagetools -->`` markers (the maps carry the navigation only);
* then the search-engine / crawler policy (``network.publication.publish``).

Each step replaces what an earlier run put between its markers, so running it twice gives the same pages.
"""

from __future__ import annotations

import datetime
import html
import json
import logging
import os
import re
from dataclasses import dataclass, field
from typing import Any

from django.conf import settings
from django.template.loader import render_to_string

from network import data_dictionary, pages, publication, workbooks
from network.parameters import PARAMETERS_FILENAME

logger = logging.getLogger(__name__)

METHODS_PAGE = "methods.html"
DATA_PAGE = data_dictionary.DATA_PAGE
DATA_AND_METHODS = "Data and methods"
# Where compare_analysis copies the compared analysis' data/ folder and its summary.json.
COMPARED_DATA_DIR = "data_2"
# Pages outside the catalogue (they have no card): their titles and the records they render.
RECORD_PAGES: dict[str, str] = {METHODS_PAGE: "Methods record", DATA_PAGE: "Data dictionary"}
RECORD_DOWNLOADS: dict[str, tuple[tuple[str, str], ...]] = {
    METHODS_PAGE: ((PARAMETERS_FILENAME, "Methods record"), ("summary.json", "Run options")),
    DATA_PAGE: ((data_dictionary.DATA_MD, "Data dictionary"),),
}

SITENAV = ("<!-- pulpit:sitenav -->", "<!-- /pulpit:sitenav -->")
PAGETOOLS = ("<!-- pulpit:pagetools -->", "<!-- /pulpit:pagetools -->")
# In a map's screen-reader summary: where the same information can be read as tables.
TABLELINKS = ("<!-- pulpit:tablelinks -->", "<!-- /pulpit:tablelinks -->")
# The tables a map's summary points at, with how the sentence names each.
MAP_TABLES: tuple[tuple[str, str], ...] = (
    ("channel_table.html", "per-channel measures"),
    ("community_table.html", "community statistics"),
    ("network_table.html", "whole-network statistics"),
)

# Format badges of the downloads, by extension.
FORMATS: dict[str, str] = {
    ".xlsx": "XLSX",
    ".csv": "CSV",
    ".gexf": "GEXF",
    ".graphml": "GraphML",
    ".md": "Markdown",
    ".json": "JSON",
}


def _esc(text: object) -> str:
    return html.escape(str(text), quote=True)


def human_size(size: int) -> str:
    """``size`` bytes as a short figure: ``812 B``, ``14 kB``, ``3.2 MB`` (decimal units)."""
    if size < 1000:
        return f"{size} B"
    value = float(size)
    for unit in ("kB", "MB", "GB"):
        value /= 1000
        # Compare what will be printed, so 999,999 B reads "1.0 MB" and never "1000 kB".
        if round(value) < 1000 or unit == "GB":
            return f"{value:.0f} {unit}" if round(value, 1) >= 10 else f"{value:.1f} {unit}"
    return f"{value:.1f} GB"  # pragma: no cover - the loop always returns


def format_of(name: str) -> str:
    return FORMATS.get(os.path.splitext(name)[1].lower(), os.path.splitext(name)[1].lstrip(".").upper())


# ── What the export holds ────────────────────────────────────────────────────


@dataclass
class Inventory:
    """The files at the root of an export, and the facts its metadata records."""

    root: str
    names: list[str]
    summary: dict[str, Any] = field(default_factory=dict)
    meta: dict[str, Any] = field(default_factory=dict)
    timeline: dict[str, Any] = field(default_factory=dict)

    @property
    def version(self) -> str:
        """The Pulpit version that made the export (the running one for an export that records none)."""
        return str(self.summary.get("pulpit_version") or getattr(settings, "APP_VERSION", ""))

    @property
    def created(self) -> str:
        """The day the export was made, ISO."""
        return _date(self.summary.get("created_at")) or datetime.date.today().isoformat()

    def has(self, name: str) -> bool:
        return name in self.names

    def size(self, name: str) -> int:
        try:
            return os.path.getsize(os.path.join(self.root, name))
        except OSError:
            return 0

    def html_pages(self) -> list[str]:
        return [name for name in self.names if name.endswith(".html")]


def _read_json(path: str) -> dict[str, Any]:
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def inventory(root: str) -> Inventory:
    names = sorted(
        name for name in os.listdir(root) if not name.startswith(".") and os.path.isfile(os.path.join(root, name))
    )
    return Inventory(
        root=root,
        names=names,
        summary=_read_json(os.path.join(root, "summary.json")),
        meta=_read_json(os.path.join(root, "data", "meta.json")),
        timeline=_read_json(os.path.join(root, "data", "timeline.json")),
    )


def is_site(root: str) -> bool:
    """Whether the export at *root* was written as a site by this layout: its landing page carries the
    navigation markers the site pass fills. An export of an earlier version does not."""
    try:
        with open(os.path.join(root, pages.LANDING_PAGE), encoding="utf-8") as f:
            return SITENAV[0] in f.read()
    except OSError:
        return False


def compared_inventory(inv: Inventory) -> Inventory:
    """The records of the compared analysis (``compare_analysis`` copies them into ``data_2/``): what the
    About sheet of a ``*_2.xlsx`` workbook states, which is that analysis' scope and not this export's."""
    folder = os.path.join(inv.root, COMPARED_DATA_DIR)
    return Inventory(
        root=inv.root,
        names=inv.names,
        summary=_read_json(os.path.join(folder, "summary.json")),
        meta=_read_json(os.path.join(folder, "meta.json")),
        timeline=_read_json(os.path.join(folder, "timeline.json")),
    )


@dataclass(frozen=True)
class NavEntry:
    file: str
    title: str


def site_pages(inv: Inventory) -> list[tuple[str, list[NavEntry]]]:
    """The export's pages as the *Contents* menu lists them: ``(group title, entries)`` in reading order."""
    present = set(inv.names)
    groups: list[tuple[str, list[NavEntry]]] = []
    for key, title in pages.GROUPS:
        entries = [
            NavEntry(page.file, page.title)
            for card in pages.CARDS
            if card.group == key
            for page in card.pages
            if page.file in present
        ]
        if key == "comparison":
            entries += [
                NavEntry(copy, pages.page_title(copy))
                for card in pages.CARDS
                for page in card.pages
                if (copy := pages.compared_name(page.file)) in present
            ]
        if entries:
            groups.append((title, entries))
    methods = [NavEntry(name, title) for name, title in RECORD_PAGES.items()]
    groups.append(
        (
            DATA_AND_METHODS,
            [NavEntry(pages.LANDING_PAGE + "#data", "All files")] + [e for e in methods if e.file in present],
        )
    )
    return groups


# ── Navigation and page tools ────────────────────────────────────────────────


def _crumb_root(project_title: str) -> str:
    return project_title or "Overview"


def nav_html(inv: Inventory, current: str, project_title: str) -> str:
    """The breadcrumb and the *Contents* menu of *current*, as inserted between the sitenav markers."""
    title = pages.page_title(current) or RECORD_PAGES.get(current, "")
    if current == pages.LANDING_PAGE or not title:
        crumbs = f'<li aria-current="page">{_esc(_crumb_root(project_title))}</li>'
    else:
        crumbs = (
            f'<li><a href="{pages.LANDING_PAGE}">{_esc(_crumb_root(project_title))}</a></li>'
            f'<li aria-current="page">{_esc(title)}</li>'
        )
    groups = []
    for group_title, entries in site_pages(inv):
        links = []
        for entry in entries:
            here = entry.file == current
            attrs = ' aria-current="page"' if here else ""
            links.append(
                f'<a class="dropdown-item{" active" if here else ""}" href="{_esc(entry.file)}"{attrs}>{_esc(entry.title)}</a>'
            )
        groups.append(
            f'<div class="export-contents-group"><p class="export-contents-head">{_esc(group_title)}</p>{"".join(links)}</div>'
        )
    overview_attrs = ' aria-current="page"' if current == pages.LANDING_PAGE else ""
    return (
        f'<ol class="export-crumbs" aria-label="Breadcrumb">{crumbs}</ol>'
        '<div class="dropdown export-contents">'
        '<button type="button" class="btn btn-sm export-contents-toggle dropdown-toggle" data-bs-toggle="dropdown" '
        'aria-expanded="false"><i class="bi bi-list" aria-hidden="true"></i> Contents</button>'
        '<div class="dropdown-menu dropdown-menu-end export-contents-menu">'
        f'<a class="dropdown-item export-contents-overview" href="{pages.LANDING_PAGE}"{overview_attrs}>'
        '<i class="bi bi-house" aria-hidden="true"></i> Overview</a>'
        f'<div class="export-contents-grid">{"".join(groups)}</div>'
        "</div></div>"
    )


def page_downloads(inv: Inventory, page: str) -> list[tuple[str, str]]:
    """``(file, label)`` of the downloads of *page* (its card's files that exist), in catalogue order."""
    found = pages.lookup(page)
    if found is None:
        return [(name, label) for name, label in RECORD_DOWNLOADS.get(page, ()) if inv.has(name)]
    card, _entry, compared = found
    return pages.downloads_of(card, inv.names, compared=compared)


def _download_item(inv: Inventory, name: str, label: str) -> str:
    return (
        f'<li><a class="dropdown-item export-download" href="{_esc(name)}" download>'
        f'<span class="export-format">{_esc(format_of(name))}</span>'
        f'<span class="export-download-name">{_esc(label)}<span class="export-download-file">{_esc(name)}</span></span>'
        f'<span class="export-size">{_esc(human_size(inv.size(name)))}</span></a></li>'
    )


def downloads_menu(inv: Inventory, files: list[tuple[str, str]], label: str = "Download", *, chip: bool = False) -> str:
    """A menu of downloads. ``chip``: the compact form of a landing card, whose label is a file format."""
    if not files:
        return ""
    items = "".join(_download_item(inv, name, file_label) for name, file_label in files)
    if chip:
        button = (
            '<button type="button" class="btn btn-outline-secondary btn-sm dropdown-toggle" data-bs-toggle="dropdown" '
            f'aria-expanded="false" title="Download {_esc(label)}" aria-label="Download {_esc(label)} files">'
            f"{_esc(label)}</button>"
        )
    else:
        button = (
            '<button type="button" class="btn btn-outline-secondary btn-sm dropdown-toggle" data-bs-toggle="dropdown" '
            f'aria-expanded="false"><i class="bi bi-download" aria-hidden="true"></i> {_esc(label)}</button>'
        )
    return (
        f'<div class="dropdown d-inline-block">{button}'
        f'<ul class="dropdown-menu dropdown-menu-end export-downloads">{items}</ul></div>'
    )


def _method_url(inv: Inventory, card: pages.Card) -> str:
    """The card's method document as it stood in the version that made the export, whatever version re-runs
    the site pass later (``compare_analysis``)."""
    return pages.docs_url(getattr(settings, "REPOSITORY_URL", ""), inv.version, card.doc)


def tools_html(inv: Inventory, page: str) -> str:
    """The method link and the downloads of *page*, as inserted between the pagetools markers."""
    found = pages.lookup(page)
    parts = []
    if found is not None:
        url = _method_url(inv, found[0])
        if url:
            parts.append(
                f'<a href="{_esc(url)}" target="_blank" rel="noopener noreferrer" class="btn btn-outline-secondary btn-sm">'
                '<i class="bi bi-book" aria-hidden="true"></i> Method</a>'
            )
    parts.append(downloads_menu(inv, page_downloads(inv, page)))
    return "".join(parts)


def table_links_html(inv: Inventory, page: str) -> str:
    """Where a map's content can be read as tables: the tables the export holds (a compared map points at the
    compared copies), else the overview page, so the sentence never links to a page that is not there."""
    compared = pages.original_name(page) is not None
    links = []
    for name, text in MAP_TABLES:
        target = pages.compared_name(name) if compared else name
        if inv.has(target):
            links.append(f'<a href="{_esc(target)}">{_esc(text)}</a>')
    if not links:
        return f'from the <a href="{pages.LANDING_PAGE}">overview page</a>'
    listed = links[0] if len(links) == 1 else ", ".join(links[:-1]) + " and " + links[-1]
    return f"in {'this table' if len(links) == 1 else 'these tables'}: {listed}"


def _replace_between(content: str, markers: tuple[str, str], inner: str) -> str:
    start, end = markers
    pattern = re.compile(re.escape(start) + r".*?" + re.escape(end), re.S)
    return pattern.sub(lambda _m: start + inner + end, content, count=1)


def apply_navigation(inv: Inventory, project_title: str) -> None:
    """Fill the sitenav and pagetools markers of every page of the export."""
    for page in inv.html_pages():
        path = os.path.join(inv.root, page)
        with open(path, encoding="utf-8") as f:
            content = f.read()
        updated = _replace_between(content, SITENAV, nav_html(inv, page, project_title))
        if page != pages.LANDING_PAGE:
            updated = _replace_between(updated, PAGETOOLS, tools_html(inv, page))
        updated = _replace_between(updated, TABLELINKS, table_links_html(inv, page))
        if updated != content:
            with open(path, "w", encoding="utf-8") as f:
                f.write(updated)


# ── The landing page ─────────────────────────────────────────────────────────


def _date(value: str | None) -> str:
    return (value or "")[:10]


def _period_label(inv: Inventory) -> str:
    """The days the analysis covers: the requested bounds, an open side filled with the analysed messages'
    own first / last day (never a timeline period's calendar edge, which can lie beyond the data)."""
    start, end = publication.analysed_range(inv.summary)
    if start and end:
        return f"{start} – {end}"
    if start:
        return f"from {start}"
    if end:
        return f"up to {end}"
    return "all stored messages"


def _ties_counted(options: dict[str, Any]) -> str:
    kinds = ["forwards"]
    if options.get("include_mentions"):
        kinds.append("mentions")
    if options.get("near_copy_edges"):
        kinds.append("near-copies of text")
    if options.get("image_copy_edges"):
        kinds.append("image copies")
    text = ", ".join(kinds[:-1]) + (" and " if len(kinds) > 1 else "") + kinds[-1]
    return text[0].upper() + text[1:]


def study_facts(inv: Inventory) -> list[tuple[str, str]]:
    """The landing page's study header, as ``(label, value)`` rows."""
    options = inv.summary.get("options") or {}
    facts: list[tuple[str, str]] = []
    nodes = inv.summary.get("nodes", inv.meta.get("total_nodes"))
    edges = inv.summary.get("edges", inv.meta.get("total_edges"))
    if isinstance(nodes, int):
        facts.append(("Channels", f"{nodes:,}"))
    if isinstance(edges, int):
        facts.append(("Ties", f"{edges:,}"))
    facts.append(("Period", _period_label(inv)))
    facts.append(("A tie is", f"{_ties_counted(options)}, from the citing channel to the cited one"))
    if inv.meta.get("edge_weight_label"):
        facts.append(("Tie weight", str(inv.meta["edge_weight_label"]).capitalize()))
    periods = inv.timeline.get("periods") or []
    if periods:
        step = inv.timeline.get("step") or "year"
        window = inv.timeline.get("window_months")
        per = f"{len(periods)} periods by {step}" + (f", {window}-month sliding windows" if window else "")
        facts.append(("Timeline", per))
    facts.append(("Generated", f"{inv.created} with Pulpit {inv.version}".strip()))
    return facts


SOFTWARE_TITLE = "Pulpit"


def _cff_authors() -> tuple[list[str], str]:
    """The software's authors (``Family, G.``) and its title, from the repository's ``CITATION.cff``.

    Only names and the title are read: the file's contact details never reach an export.
    """
    try:
        with open(os.path.join(str(settings.BASE_DIR), "CITATION.cff"), encoding="utf-8") as f:
            lines = f.read().splitlines()
    except OSError:
        return [], SOFTWARE_TITLE
    authors: list[list[str]] = []
    title = SOFTWARE_TITLE
    in_authors = False
    for line in lines:
        if not line.startswith((" ", "-")):
            in_authors = line.startswith("authors:")
            if line.startswith("title:"):
                title = line.partition(":")[2].strip().strip('"') or SOFTWARE_TITLE
            continue
        if not in_authors:
            continue
        if line.lstrip().startswith("- "):
            authors.append(["", ""])
            line = line.replace("- ", "", 1)
        key, _, value = line.strip().partition(":")
        if authors and key in ("family-names", "given-names"):
            authors[-1][0 if key == "family-names" else 1] = value.strip().strip('"')
    names = []
    for family, given in authors:
        if family:
            initials = " ".join(f"{part[0]}." for part in given.split())
            names.append(f"{family}, {initials}" if initials else family)
    return names, title


def citations(inv: Inventory, project_title: str, public_url: str) -> dict[str, str]:
    """Suggested citations of the analysis and of the software that produced it."""
    created, version = inv.created, inv.version
    nodes = inv.summary.get("nodes")
    subject = f"Network analysis of {nodes:,} Telegram channels" if isinstance(nodes, int) else "Network analysis"
    analysis = f"{project_title or 'Untitled analysis'}. {subject}, {_period_label(inv)}. Generated {created} with Pulpit {version}."
    if public_url:
        analysis += f" {public_url}"
    authors, title = _cff_authors()
    repository = getattr(settings, "REPOSITORY_URL", "")
    who = " & ".join(authors) if authors else "Pulpit contributors"
    # The year and the version are those of the build that made the export, which is what a reader must cite
    # to find the same methods (the citation file's own date is that of the last tagged release).
    software = f"{who} ({created[:4]}). {title} (Version {version}) [Computer software]. {repository}".strip()
    return {"analysis": analysis, "software": software}


def _card_context(inv: Inventory, card: pages.Card) -> dict[str, Any] | None:
    present = [page for page in card.pages if inv.has(page.file)]
    downloads = pages.downloads_of(card, inv.names)
    if not present and not downloads:
        return None
    by_format: dict[str, list[tuple[str, str]]] = {}
    for name, label in downloads:
        by_format.setdefault(format_of(name), []).append((name, label))
    formats = []
    for fmt, files in by_format.items():
        if len(files) == 1:
            formats.append({"label": fmt, "href": files[0][0], "menu": ""})
        else:
            formats.append({"label": fmt, "href": "", "menu": downloads_menu(inv, files, label=fmt, chip=True)})
    return {
        "key": card.key,
        "title": card.title,
        "icon": card.icon,
        "summary": card.summary,
        "pages": [
            {
                "href": page.file,
                "label": "Open" if len(present) == 1 else ("Open 3D" if "(3D)" in page.title else "Open 2D"),
            }
            for page in present
        ],
        "formats": formats,
        "doc_url": _method_url(inv, card),
    }


def _compared_card(inv: Inventory) -> dict[str, Any] | None:
    entries = [
        {"href": pages.compared_name(page.file), "label": page.title}
        for card in pages.CARDS
        for page in card.pages
        if inv.has(pages.compared_name(page.file))
    ]
    downloads = [
        (pages.compared_name(d.pattern), f"{d.label} (compared analysis)")
        for card in pages.CARDS
        for d in card.downloads
        if inv.has(pages.compared_name(d.pattern))
    ]
    if not entries and not downloads:
        return None
    return {
        "key": "compared",
        "title": "The compared analysis",
        "icon": "layers",
        "summary": "The other analysis' own pages and tables, copied in so the two can be read side by side.",
        "links": entries,
        "formats": [{"label": "Download", "href": "", "menu": downloads_menu(inv, downloads)}] if downloads else [],
        "pages": [],
        "doc_url": "",
    }


# Above this many periods the landing page's period table starts folded: a monthly timeline over several
# years would otherwise push the file list far down the page.
PERIODS_OPEN_MAX = 12


def _count(value: Any) -> str:
    return f"{value:,}" if isinstance(value, int) and not isinstance(value, bool) else "—"


def _periods(inv: Inventory) -> dict[str, Any] | None:
    """The timeline as the landing page lists it; ``None`` without a timeline.

    ``key`` is what the *Period* column of the spreadsheets and CSVs holds and what names the period's
    ``data_<key>/`` folder: for sliding windows it is the step the window ends with, so it is listed beside
    the window's label and dates.
    """
    periods = inv.timeline.get("periods") or []
    if not periods:
        return None
    rows = [
        {
            "key": str(period.get("key") or ""),
            "label": period.get("label") or period.get("key"),
            "start": _date(period.get("start")),
            "end": _date(period.get("end")),
            "nodes": _count(period.get("nodes")),
            "edges": _count(period.get("edges")),
        }
        for period in periods
    ]
    step = inv.timeline.get("step") or "year"
    window = inv.timeline.get("window_months")
    return {
        "rows": rows,
        "summary": f"{len(rows)} periods by {step}" + (f", {window}-month sliding windows" if window else ""),
        "show_key": any(row["key"] != row["label"] for row in rows),
        "open": len(rows) <= PERIODS_OPEN_MAX,
        "overlapping": bool(inv.timeline.get("overlapping")),
    }


def _file_rows(inv: Inventory) -> list[dict[str, Any]]:
    """The *Data and methods* table: every downloadable file of the export, grouped by kind."""
    kinds = data_dictionary.file_groups(inv.root, inv.names)
    rows = []
    for kind, files in kinds:
        rows.append({"group": kind})
        for name in files:
            # A row is a file, a folder, or a family of them listed once ("data_<period>/"): a file is
            # downloaded, anything else opens its entry in the data dictionary.
            row = data_dictionary.listed_file(inv.root, name)
            rows.append(
                {
                    "name": name,
                    "href": row["download"] or f"{DATA_PAGE}#{row['anchor']}",
                    "download": bool(row["download"]),
                    "format": "Folder" if row["folder"] else format_of(name),
                    "size": human_size(row["size"]),
                    "description": row["description"],
                    "dictionary": f"{DATA_PAGE}#{row['anchor']}" if row["columns"] else "",
                }
            )
    return rows


def write_index(inv: Inventory, *, project_title: str, seo: bool, public_url: str) -> None:
    from network import tables  # imported here: tables imports pages, and site is imported by the commands only

    groups = []
    for key, title in pages.GROUPS:
        cards = [ctx for card in pages.CARDS if card.group == key and (ctx := _card_context(inv, card))]
        if key == "comparison" and (compared := _compared_card(inv)):
            cards.append(compared)
        if cards:
            groups.append({"key": key, "title": title, "cards": cards})
    context = {
        **tables.page_context(
            pages.LANDING_PAGE, project_title, title="Overview", generated=inv.created, app_version=inv.version
        ),
        "title": project_title or "Network analysis",
        "robots_meta": publication.robots_content(seo),
        "groups": groups,
        "timeline": _periods(inv),
        "facts": study_facts(inv),
        "files": _file_rows(inv),
        "has_methods": inv.has(METHODS_PAGE),
        "has_data_page": inv.has(DATA_PAGE),
        "citations": citations(inv, project_title, public_url),
    }
    with open(os.path.join(inv.root, pages.LANDING_PAGE), "w", encoding="utf-8") as f:
        f.write(render_to_string("network/index.html", context))


# ── methods.html: PARAMETERS.md as a page ────────────────────────────────────

_INLINE_CODE = re.compile(r"`([^`]+)`")
_BOLD = re.compile(r"\*\*([^*]+)\*\*")
_EM = re.compile(r"(?<![*\w])\*([^*\n]+)\*(?![*\w])")
_LINK = re.compile(r"\[([^\]]+)\]\(([^)\s]+)\)")


def _inline(text: str) -> str:
    """Escaped *text* with the inline Markdown the parameters record uses: code, bold, italics, links."""
    codes: list[str] = []

    def keep(match: re.Match) -> str:
        codes.append(f"<code>{html.escape(match.group(1))}</code>")
        return f"\x00{len(codes) - 1}\x00"

    text = _INLINE_CODE.sub(keep, text)
    text = html.escape(text, quote=False)
    text = _BOLD.sub(r"<strong>\1</strong>", text)
    text = _EM.sub(r"<em>\1</em>", text)
    text = _LINK.sub(_link, text)
    return re.sub(r"\x00(\d+)\x00", lambda m: codes[int(m.group(1))], text)


_SAFE_HREF = re.compile(r"^(https?://|mailto:|#|[\w./-]+$)", re.I)


def _link(match: re.Match) -> str:
    """A Markdown link of already-escaped text: kept only for web, mail, anchor and relative addresses (a label
    group's name reaches the record, so nothing here may become a ``javascript:`` link)."""
    label, href = match.group(1), html.unescape(match.group(2))
    if not _SAFE_HREF.match(href):
        return match.group(0)
    return f'<a href="{html.escape(href, quote=True)}">{label}</a>'


def _split_row(line: str) -> list[str]:
    cells = re.split(r"(?<!\\)\|", line.strip().strip("|"))
    return [cell.strip().replace("\\|", "|") for cell in cells]


def markdown_to_html(text: str) -> str:
    """The Markdown subset of ``PARAMETERS.md`` as HTML: headings, paragraphs, bullet lists and pipe tables."""
    out: list[str] = []
    lines = text.splitlines()
    i = 0
    paragraph: list[str] = []
    used_ids: set[str] = set()
    section = ""  # slug of the current "##" section: sub-headings repeat across sections ("Measures", "Layout")

    def flush() -> None:
        if paragraph:
            out.append(f"<p>{_inline(' '.join(paragraph))}</p>")
            paragraph.clear()

    while i < len(lines):
        line = lines[i]
        stripped = line.strip()
        heading = re.match(r"^(#{1,6})\s+(.*)$", stripped)
        if not stripped:
            flush()
        elif heading:
            flush()
            # The record's own title is the page title: its "#" is dropped, "##" becomes the page's h2.
            level = len(heading.group(1))
            if level > 1:
                slug = re.sub(r"[^a-z0-9]+", "-", heading.group(2).lower()).strip("-") or "section"
                if level == 2:
                    section = slug
                elif section:
                    slug = f"{section}-{slug}"
                base, n = slug, 2
                while slug in used_ids:
                    slug, n = f"{base}-{n}", n + 1
                used_ids.add(slug)
                out.append(f'<h{level} id="{slug}">{_inline(heading.group(2))}</h{level}>')
        elif stripped.startswith("|") and i + 1 < len(lines) and re.match(r"^\|?\s*:?-{3,}", lines[i + 1].strip()):
            flush()
            header = _split_row(stripped)
            i += 2
            body = []
            while i < len(lines) and lines[i].strip().startswith("|"):
                body.append(_split_row(lines[i]))
                i += 1
            head_html = "".join(f"<th>{_inline(cell)}</th>" for cell in header)
            rows_html = "".join("<tr>" + "".join(f"<td>{_inline(c)}</td>" for c in row) + "</tr>" for row in body)
            out.append(
                '<div class="table-responsive"><table class="table table-sm export-record-table">'
                f"<thead><tr>{head_html}</tr></thead><tbody>{rows_html}</tbody></table></div>"
            )
            continue
        elif re.match(r"^[-*]\s+", stripped):
            flush()
            items = []
            while i < len(lines) and re.match(r"^[-*]\s+", lines[i].strip()):
                items.append(f"<li>{_inline(re.sub(r'^[-*]\\s+', '', lines[i].strip()))}</li>")
                i += 1
            out.append(f"<ul>{''.join(items)}</ul>")
            continue
        else:
            paragraph.append(stripped)
        i += 1
    flush()
    return "\n".join(out)


def write_methods_page(inv: Inventory, *, project_title: str, seo: bool) -> bool:
    """Write ``methods.html`` from ``PARAMETERS.md``; ``False`` when the export has no parameters record."""
    from network import tables

    path = os.path.join(inv.root, PARAMETERS_FILENAME)
    try:
        with open(path, encoding="utf-8") as f:
            text = f.read()
    except OSError:
        return False
    context = {
        **tables.page_context(
            METHODS_PAGE,
            project_title,
            title=RECORD_PAGES[METHODS_PAGE],
            description="Every parameter behind the numbers of this analysis: the run options, the fixed parameters "
            "and the software versions.",
            generated=inv.created,
            app_version=inv.version,
        ),
        "robots_meta": publication.robots_content(seo),
        "body": markdown_to_html(text),
        "source": PARAMETERS_FILENAME,
    }
    context["page"]["question"] = "Which options, fixed parameters and software produced these numbers?"
    with open(os.path.join(inv.root, METHODS_PAGE), "w", encoding="utf-8") as f:
        f.write(render_to_string("network/methods.html", context))
    return True


# ── Workbooks ────────────────────────────────────────────────────────────────


def finish_workbooks(inv: Inventory, project_title: str) -> None:
    """Format every workbook of the export and give it its About sheet (``network.workbooks``)."""
    compared = compared_inventory(inv)
    for name in inv.names:
        if not name.endswith(".xlsx"):
            continue
        found = None
        is_compared = pages.original_name(name) is not None
        original = pages.original_name(name) or name
        for card in pages.CARDS:
            if any(d.pattern == original for d in card.downloads):
                found = card
                break
        title = found.title if found else os.path.splitext(name)[0].replace("_", " ").capitalize()
        if is_compared:
            title += " (compared analysis)"
        # A compared workbook describes the analysis it came from, not the export it was copied into.
        scope = compared if is_compared else inv
        about = {
            "title": " — ".join(part for part in (project_title, title) if part),
            "description": data_dictionary.describe_file(name),
            "facts": study_facts(scope),
            "method_url": _method_url(scope, found) if found else "",
            "dictionary_url": f"{DATA_PAGE}#{data_dictionary.anchor(name)}",
        }
        try:
            workbooks.finish(os.path.join(inv.root, name), name, about)
        except Exception as exc:  # a workbook that cannot be reopened keeps its plain layout
            logger.warning("Could not finish workbook %s: %s", name, exc)


# ── Everything, in order ─────────────────────────────────────────────────────


def finalise(root: str, *, project_title: str = "", seo: bool = False, public_url: str = "") -> list[str]:
    """Assemble the export at *root* as a site, then apply the publication policy.

    Returns the server files the publication pass wrote (``robots.txt``, …).
    """
    if not os.path.isdir(root):
        return []
    write_methods_page(inventory(root), project_title=project_title, seo=seo)
    finish_workbooks(inventory(root), project_title)
    data_dictionary.write(root, project_title=project_title, seo=seo)
    write_index(inventory(root), project_title=project_title, seo=seo, public_url=public_url)
    apply_navigation(inventory(root), project_title)
    return publication.publish(root, seo=seo, public_url=public_url, site_name=project_title)
