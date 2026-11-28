"""The data dictionary of an export: what every file holds and what every column means.

``write`` produces ``DATA.md`` (plain text, at the export root) and ``data.html`` (the same as a page of the
export), from the files actually on disk: their columns are read from the CSV header rows and the
spreadsheets' header rows, so the dictionary cannot drift from what the writers produce.

A file is described by :data:`FILES`. A column is described where it stands: :data:`TABLES` names the table
a file (or a sheet of a workbook) holds and :data:`TABLE_COLUMNS` says what a column means *in that table*;
only then do the general :data:`COLUMNS` / :data:`COLUMN_PATTERNS` answer. All of them are keyed by the
column's snake_case form (:func:`column_key`), so a spreadsheet header and its CSV counterpart share one
entry. The workbooks' *About* sheets read the same descriptions (:func:`describe_column`).

A file that cannot be read is listed with a note instead of its columns: the dictionary is written at the very
end of an export and never aborts it.
"""

from __future__ import annotations

import csv
import fnmatch
import json
import logging
import os
import re
import unicodedata
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger(__name__)

DATA_PAGE = "data.html"
DATA_MD = "DATA.md"
ABOUT_SHEET = "About"

METHODS_GROUP = "Methods and records"
SPREADSHEETS_GROUP = "Spreadsheets"
CSV_GROUP = "CSV tables"
NETWORK_GROUP = "Network files"
FOLDERS_GROUP = "Folders"
GROUP_ORDER = (METHODS_GROUP, SPREADSHEETS_GROUP, CSV_GROUP, NETWORK_GROUP, FOLDERS_GROUP)

# What the dictionary says of a table it could not open.
UNREADABLE_NOTE = "This file could not be read, so its columns are not listed."

# (name or fnmatch pattern relative to the export root, group, description). First match wins; a compared copy
# (``x_2.ext``) reads its original's entry. A folder ends with "/"; a pattern with a "/" inside is a file of a
# folder, listed (and its columns described) when it exists.
FILES: tuple[tuple[str, str, str], ...] = (
    (
        "PARAMETERS.md",
        METHODS_GROUP,
        "The methods record: every run option, fixed parameter and software version behind the numbers "
        "(also shown as the Methods record page).",
    ),
    (DATA_MD, METHODS_GROUP, "This data dictionary, as plain text."),
    (
        "summary.json",
        METHODS_GROUP,
        "The run's options and headline counts, machine-readable, for reproducing the run.",
    ),
    (
        "dyads/README.md",
        METHODS_GROUP,
        "What each file of the dyads/ bundle holds and how the network-modelling packages read it.",
    ),
    (
        "channel_table.xlsx",
        SPREADSHEETS_GROUP,
        "Channels: one row per channel, with its activity, measures and communities.",
    ),
    (
        "network_table.xlsx",
        SPREADSHEETS_GROUP,
        "Whole-network statistics, modularity and agreement of the grouping methods, homophily and citation flows "
        "by label group, and the dyadic regression.",
    ),
    (
        "community_table.xlsx",
        SPREADSHEETS_GROUP,
        "Community statistics: one row per community of every grouping method.",
    ),
    (
        "robustness_table.xlsx",
        SPREADSHEETS_GROUP,
        "Robustness: the summary per attack strategy, the residual-size curves and the scenario tables.",
    ),
    (
        "dominance.xlsx",
        SPREADSHEETS_GROUP,
        "Dominance: the ranking of the channels, every pair and the hierarchy tests.",
    ),
    ("event_impact.xlsx", SPREADSHEETS_GROUP, "Event impact: the effects of each event and the weekly series."),
    (
        "links.xlsx",
        SPREADSHEETS_GROUP,
        "Outbound links: channels, sites, categories, co-linking pairs and label matrices.",
    ),
    ("audience.xlsx", SPREADSHEETS_GROUP, "Audience: the summary and the tables of each section."),
    ("nodes.csv", CSV_GROUP, "One row per channel: the channel table as CSV."),
    ("edges.csv", CSV_GROUP, "One row per tie: citing channel, cited channel, weight and its components."),
    ("network_label_flows.csv", CSV_GROUP, "Citations from label to label, against chance, for every label group."),
    ("dominance_channels.csv", CSV_GROUP, "Dominance ranking and role of each channel."),
    ("dominance_pairs.csv", CSV_GROUP, "Dependence of each pair of channels with a citation between them."),
    ("event_impact.csv", CSV_GROUP, "Level and slope change of each metric around each event."),
    ("links_channel_sites.csv", CSV_GROUP, "Messages of each channel linking to each site."),
    ("links_colinking.csv", CSV_GROUP, "Pairs of channels linking to the same sites, against chance."),
    (
        "audience_participation.csv",
        CSV_GROUP,
        "Per channel: its commenters, their replies and how unevenly the replies are spread over them.",
    ),
    (
        "audience_breadth.csv",
        CSV_GROUP,
        "Per label: its commenters, their replies and the share of them commenting under another label too.",
    ),
    ("audience_overlap.csv", CSV_GROUP, "Pairs of channels sharing commenters, against chance."),
    (
        "audience_retention.csv",
        CSV_GROUP,
        "Per month: the accounts commenting, those commenting for the first time and the channels commented on.",
    ),
    (
        "audience_channel_commenters.csv",
        CSV_GROUP,
        "Comments channels wrote in their own name under other channels' posts, one row per pair of channels.",
    ),
    (
        "data/near_copies.csv",
        CSV_GROUP,
        "The near-copies of text counted as citations: one row per copying message and the earlier message it "
        "repeats (each period folder holds its own list).",
    ),
    (
        "data/image_copies.csv",
        CSV_GROUP,
        "The image copies counted as citations: one row per copying picture post and the earlier post showing "
        "the same image (each period folder holds its own list).",
    ),
    ("dyads/actors.csv", CSV_GROUP, "Dyadic export: every channel of the network with its labels and covariates."),
    ("dyads/edgelist.csv", CSV_GROUP, "Dyadic export: every tie with its raw citation counts."),
    ("dyads/events.csv", CSV_GROUP, "Dyadic export: every citation counted on a tie, timestamped, in time order."),
    (
        "dyads/dyads.csv",
        CSV_GROUP,
        "Dyadic export: one row per ordered pair of channels of the dyadic regression, with its dependent "
        "variables and predictors.",
    ),
    (
        "dyads/waves/presence.csv",
        CSV_GROUP,
        "Dyadic export: which channels are part of the network of each timeline period.",
    ),
    (
        "dyads/waves/wave_*.csv",
        CSV_GROUP,
        "Dyadic export: the network of one timeline period as a 0/1 matrix (row = citing channel, column = cited "
        "channel), one file per period",
    ),
    ("network.gexf", NETWORK_GROUP, "The network for Gephi: channels with their attributes, ties with their weights."),
    ("network.graphml", NETWORK_GROUP, "The network for igraph, NetworkX, Cytoscape and other GraphML readers."),
    (
        "data/",
        FOLDERS_GROUP,
        "The JSON the pages read (channels, positions, communities, each analysis' results), and the "
        "near-copy and image-copy audit lists when those options ran.",
    ),
    ("data_coordination/", FOLDERS_GROUP, "The coordination maps' data."),
    (
        "data_coordination_*/",
        FOLDERS_GROUP,
        "The coordination maps' data for each timeline period with coordination ties, one folder per period",
    ),
    ("data_2/", FOLDERS_GROUP, "The compared analysis' data."),
    (
        "data_*/",
        FOLDERS_GROUP,
        "The pages' data for each period of the timeline, laid out as data/, one folder per period",
    ),
    (
        "dyads/",
        FOLDERS_GROUP,
        "The network as data for network-modelling tools (ERGM, relational event models, RSiena): actors, ties, "
        "timestamped events and one network per period.",
    ),
    ("media/", FOLDERS_GROUP, "The channel pictures the maps show."),
)


@dataclass(frozen=True)
class Family:
    """Files or folders that come one per timeline period and are listed as one row.

    ``name`` is the row's name (``data_<period>/``), ``pattern`` the :data:`FILES` pattern its members match.
    """

    name: str
    pattern: str


FAMILIES: tuple[Family, ...] = (
    Family("data_coordination_<period>/", "data_coordination_*/"),
    Family("data_<period>/", "data_*/"),
    Family("dyads/waves/wave_<period>.csv", "dyads/waves/wave_*.csv"),
)
_FAMILY_BY_NAME = {family.name: family for family in FAMILIES}
_FAMILY_BY_PATTERN = {family.pattern: family for family in FAMILIES}


def _original(name: str) -> str:
    stem, dot, ext = name.rpartition(".")
    if dot and stem.endswith("_2"):
        return f"{stem[:-2]}.{ext}"
    return name


def _file_pattern(name: str) -> str | None:
    """The :data:`FILES` pattern that describes *name*: the first one matching."""
    lookup = _original(name)
    for pattern, _group, _description in FILES:
        if fnmatch.fnmatchcase(lookup, pattern):
            return pattern
    return None


def _file_entry(name: str) -> tuple[str, str] | None:
    pattern = _file_pattern(name)
    if pattern is None:
        return None
    return next((group, description) for entry, group, description in FILES if entry == pattern)


def family_members(root: str, name: str) -> list[str]:
    """The files or folders of the export at *root* that the family row *name* stands for, in order.

    ``[]`` for a name that is not a family row (``data_<period>/`` is one; ``data_2024/`` is not).
    """
    family = _FAMILY_BY_NAME.get(name)
    if family is None or not root:
        return []
    folder = os.path.dirname(family.pattern.rstrip("/"))
    try:
        entries = list(os.scandir(os.path.join(root, folder) if folder else root))
    except OSError:
        return []
    wants_folders = family.pattern.endswith("/")
    prefix = f"{folder}/" if folder else ""
    candidates = [
        prefix + entry.name + ("/" if wants_folders else "") for entry in entries if entry.is_dir() == wants_folders
    ]
    return sorted(candidate for candidate in candidates if _file_pattern(candidate) == family.pattern)


def _member_summary(members: list[str]) -> str:
    """``7 folders, data_2020/ to data_2026/``: how many members a family row stands for, and which."""
    kind = "folder" if members[0].endswith("/") else "file"
    first, last = (
        os.path.basename(m.rstrip("/")) + ("/" if m.endswith("/") else "") for m in (members[0], members[-1])
    )
    if len(members) == 1:
        return f"1 {kind}, {first}"
    return f"{len(members)} {kind}s, {first} to {last}"


def describe_file(name: str, root: str = "") -> str:
    """What the file or folder *name* holds, ``""`` for one the dictionary does not list.

    With *root* (the export folder), the row of a family also says how many folders or files it stands for.
    """
    entry = _file_entry(name)
    if entry is None:
        return ""
    description = entry[1]
    if _original(name) != name:
        description = f"{description.rstrip('.')}, in the compared analysis."
    members = family_members(root, name)
    if members:
        return f"{description.rstrip('.')}: {_member_summary(members)}."
    return description if description.endswith(".") else description + "."


def anchor(name: str) -> str:
    return "file-" + re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")


def _tree_size(path: str) -> int:
    if os.path.isfile(path):
        try:
            return os.path.getsize(path)
        except OSError:
            return 0
    total = 0
    for dirpath, _dirs, files in os.walk(path):
        for file in files:
            try:
                total += os.path.getsize(os.path.join(dirpath, file))
            except OSError:
                pass
    return total


def _family_path(path: str) -> tuple[str, str] | None:
    """``(root, family row name)`` when *path* is ``<root>/<a family row>``, else ``None``."""
    normalised = path.replace(os.sep, "/").rstrip("/")
    for family in FAMILIES:
        tail = "/" + family.name.rstrip("/")
        if normalised.endswith(tail):
            return normalised[: -len(tail)], family.name
    return None


def folder_size(path: str) -> int:
    """Bytes under the folder *path*; for the row of a family (``<root>/data_<period>/``), under all its members."""
    if not os.path.exists(path):
        found = _family_path(path)
        if found is not None:
            root, name = found
            return sum(_tree_size(os.path.join(root, member)) for member in family_members(root, name))
    return _tree_size(path)


def _row_name(name: str) -> str:
    """The row a file or folder is listed under: its family's row, else its own name."""
    family = _FAMILY_BY_PATTERN.get(_file_pattern(name) or "")
    return family.name if family is not None else name


def _folders(root: str) -> list[str]:
    """The export's folders worth listing, the folders of a family as one row (``data_<period>/``)."""
    try:
        names = sorted(entry.name + "/" for entry in os.scandir(root) if entry.is_dir())
    except OSError:
        return []
    rows: list[str] = []
    for name in names:
        if name not in ("css/", "js/") and _file_entry(name) is not None and _row_name(name) not in rows:
            rows.append(_row_name(name))
    return rows


def _nested_files(root: str) -> list[str]:
    """The listed files that sit inside a folder of the export (``data/near_copies.csv``, the ``dyads/`` tables)
    and exist, the files of a family as one row."""
    rows: list[str] = []
    for pattern, _group, _description in FILES:
        if pattern.endswith("/") or "/" not in pattern:
            continue
        family = _FAMILY_BY_PATTERN.get(pattern)
        if family is not None:
            if family_members(root, family.name):
                rows.append(family.name)
        elif os.path.isfile(os.path.join(root, pattern)):
            rows.append(pattern)
    return rows


def file_groups(root: str, names: list[str]) -> list[tuple[str, list[str]]]:
    """The downloadable files and folders of the export, by :data:`GROUP_ORDER`; pages and assets left out.

    *names* are the files at the export root. A name of the result is a path relative to *root*, or the row of
    a family (``data_<period>/``, ``dyads/waves/wave_<period>.csv``): :func:`family_members` lists what it
    stands for, :func:`folder_size` and :func:`describe_file` accept it.
    """
    grouped: dict[str, list[str]] = {group: [] for group in GROUP_ORDER}
    for name in [*names, *_nested_files(root), *_folders(root)]:
        entry = _file_entry(name)
        if entry is not None and name not in grouped[entry[0]]:
            grouped[entry[0]].append(name)
    return [(group, sorted(files, key=str.lower)) for group, files in grouped.items() if files]


def has_columns(root: str, name: str) -> bool:
    """Whether *name* is a table of the export whose columns the dictionary lists."""
    if not name.endswith((".csv", ".xlsx")):
        return False
    return os.path.isfile(os.path.join(root, name)) or bool(family_members(root, name))


def listed_file(root: str, name: str) -> dict[str, Any]:
    """A row of :func:`file_groups` as a page lists it.

    ``name``; ``folder`` (a folder, or a family of folders); ``download`` (the path to link for a download:
    the file itself, ``""`` for a folder or a family, which have no single file); ``count`` (the folders or
    files a family row stands for, 1 otherwise); ``size`` in bytes (a family's members together);
    ``description`` (with the family's members); ``anchor`` (its entry in the dictionary) and ``columns``
    (whether the dictionary lists its columns).
    """
    path = os.path.join(root, name)
    members = family_members(root, name)
    is_file = os.path.isfile(path)
    return {
        "name": name,
        "folder": name.endswith("/"),
        "download": name if is_file else "",
        "count": len(members) or 1,
        "size": _tree_size(path) if is_file else folder_size(path),
        "description": describe_file(name, root),
        "anchor": anchor(name),
        "columns": has_columns(root, name),
    }


# ── Columns ──────────────────────────────────────────────────────────────────

# Symbols of a header spelled out in its key.
_KEY_WORDS: tuple[tuple[str, str], ...] = (("%", " pct "), ("±", " pm "), ("→", " to "), ("×", " x "))


def column_key(header: str) -> str:
    """The snake_case form of a column header: ``"In-degree (0–1)"`` → ``in_degree_0_1``.

    Letters and digits of every script are kept (a label group named in Greek or Cyrillic keeps its name), in
    their compatibility form (``R²`` → ``r2``); every other character separates words.
    """
    text = unicodedata.normalize("NFKC", str(header)).strip().lower()
    for symbol, word in _KEY_WORDS:
        text = text.replace(symbol, word)
    kept = "".join(ch if ch.isalnum() or unicodedata.category(ch).startswith("M") else "_" for ch in text)
    return re.sub(r"_+", "_", kept).strip("_")


# Which table a file, or a sheet of a workbook, holds: (file pattern, sheet pattern, table). A CSV has no sheet
# (""); a compared copy reads its original's entry; a sheet continued in "<title> (2)" is the same table.
TABLES: tuple[tuple[str, str, str], ...] = (
    ("channel_table.xlsx", "Channels", "channels"),
    ("nodes.csv", "", "channels"),
    ("edges.csv", "", "edges"),
    ("network_table.xlsx", "Statistics", "statistics"),
    ("network_table.xlsx", "Modularity", "modularity"),
    ("network_table.xlsx", "Partition comparison", "partition_comparison"),
    ("network_table.xlsx", "Homophily", "homophily"),
    ("network_table.xlsx", "Homophily by label", "homophily_labels"),
    ("network_table.xlsx", "Label flows", "label_flows"),
    ("network_label_flows.csv", "", "label_flows"),
    ("network_table.xlsx", "MRQAP models", "mrqap_models"),
    ("network_table.xlsx", "MRQAP coefficients", "mrqap_coefficients"),
    ("community_table.xlsx", "Communities", "communities"),
    ("robustness_table.xlsx", "Summary", "robustness_summary"),
    ("robustness_table.xlsx", "Curves", "robustness_curves"),
    ("robustness_table.xlsx", "Efficiency", "robustness_efficiency"),
    ("robustness_table.xlsx", "Ban waves", "ban_waves"),
    ("robustness_table.xlsx", "Modular", "modular"),
    ("robustness_table.xlsx", "Ban replay", "ban_replay"),
    ("robustness_table.xlsx", "Alpha sensitivity", "alpha_sensitivity"),
    ("dominance.xlsx", "Channels", "dominance_channels"),
    ("dominance_channels.csv", "", "dominance_channels"),
    ("dominance.xlsx", "Pairs", "dominance_pairs"),
    ("dominance_pairs.csv", "", "dominance_pairs"),
    ("dominance.xlsx", "Hierarchy", "dominance_hierarchy"),
    ("event_impact.xlsx", "Effects", "event_effects"),
    ("event_impact.csv", "", "event_effects"),
    ("event_impact.xlsx", "Weekly series", "event_series"),
    ("links.xlsx", "Channels", "links_channels"),
    ("links.xlsx", "Sites", "links_sites"),
    ("links.xlsx", "Categories", "links_categories"),
    ("links.xlsx", "Co-linking", "links_colinking"),
    ("links_colinking.csv", "", "links_colinking"),
    ("links.xlsx", "Channel sites", "links_channel_sites"),
    ("links_channel_sites.csv", "", "links_channel_sites"),
    ("links.xlsx", "Matrix*", "links_matrix"),
    ("audience.xlsx", "Summary", "audience_summary"),
    ("audience.xlsx", "Participation", "audience_participation"),
    ("audience_participation.csv", "", "audience_participation"),
    ("audience.xlsx", "Activity", "audience_activity"),
    ("audience.xlsx", "Breadth labels", "audience_breadth_labels"),
    ("audience_breadth.csv", "", "audience_breadth_labels"),
    ("audience.xlsx", "Breadth classes", "audience_breadth_classes"),
    ("audience.xlsx", "Overlap pairs", "audience_overlap_pairs"),
    ("audience_overlap.csv", "", "audience_overlap_pairs"),
    ("audience.xlsx", "Overlap channels", "audience_overlap_channels"),
    ("audience.xlsx", "Overlap labels", "audience_overlap_labels"),
    ("audience.xlsx", "Retention by month", "audience_retention"),
    ("audience_retention.csv", "", "audience_retention"),
    ("audience.xlsx", "Cohorts", "audience_cohorts"),
    ("audience.xlsx", "Channel commenters", "audience_channel_commenters"),
    ("audience_channel_commenters.csv", "", "audience_channel_commenters"),
    ("data/near_copies.csv", "", "near_copies"),
    ("data/image_copies.csv", "", "image_copies"),
    ("dyads/actors.csv", "", "dyads_actors"),
    ("dyads/edgelist.csv", "", "dyads_edgelist"),
    ("dyads/events.csv", "", "dyads_events"),
    ("dyads/dyads.csv", "", "dyads_dyads"),
    ("dyads/waves/presence.csv", "", "dyads_presence"),
    ("dyads/waves/wave_*.csv", "", "dyads_wave"),
)

# Marks the workbook writers add to a sheet title: " (2)" for the continuation of a table too long for one sheet,
# " ~2" for a title that would otherwise repeat another's.
_SHEET_MARKS = re.compile(r"(?: ~\d+| \(\d+\))+$")
_SHEET_CONTINUATION = re.compile(r" \(\d+\)(?: ~\d+)?$")


def _sheet_base(sheet: str) -> str:
    return _SHEET_MARKS.sub("", sheet)


def table_of(file: str, sheet: str = "") -> str:
    """The table (:data:`TABLES`) the file *file*, or its sheet *sheet*, holds; ``""`` for one not listed."""
    lookup, base = _original(file), _sheet_base(sheet)
    for file_pattern, sheet_pattern, table in TABLES:
        if fnmatch.fnmatchcase(lookup, file_pattern) and fnmatch.fnmatchcase(base, sheet_pattern):
            return table
    return ""


_P_PERMUTATION = (
    "Two-sided p-value over the random relabellings: the share of them at least as extreme as the observed value "
    "(add-one corrected)."
)
_Z_PERMUTATION = "z-score of the observed value against the random relabellings: (observed − their mean) / their SD."
_PAIR_COMMENTERS_P = (
    "p-value of sharing at least that many commenters by chance, every account keeping the number of channels "
    "it comments on."
)
_BH_PAIRS = "Benjamini–Hochberg q-value: the p-value corrected for the number of pairs tested."
_FIRST_OF_PAIR = "of the pair's first channel"
_SECOND_OF_PAIR = "of the pair's second channel"
_COPY_CHANNEL = "The copying channel's name."
_COPY_CHANNEL_ID = "Pulpit's id of the copying channel (the citing side of the tie)."
_ORIGIN_CHANNEL = "Name of the channel of the earlier post."
_ORIGIN_CHANNEL_ID = "Pulpit's id of the channel of the earlier post (the cited side of the tie)."
_SELF_COPY = "1 when both posts are the same channel's (it re-posted itself), else 0."
_SENDER = "Pulpit's id of the citing channel (the id column of actors.csv)."
_RECEIVER = "Pulpit's id of the cited channel."

# What a column means in one table (:data:`TABLES`): (regular expression over the column key, description), the
# first match winning, consulted before the general COLUMNS / COLUMN_PATTERNS. A key is listed here when it
# means something else, or something more precise, than it does in general.
TABLE_COLUMNS: dict[str, tuple[tuple[str, str], ...]] = {
    "channels": (
        (
            r"label",
            "The channel's label in the primary label group: the one it held longest inside the analysed period.",
        ),
        (
            r"label_.+",
            "The channel's label in the label group the column is named after: the one it held longest inside "
            "the analysed period.",
        ),
        (
            r"community_.+",
            "The number of the channel's community under the grouping method the column is named after (the "
            "community table lists the communities of each method).",
        ),
        (
            r"reciprocity",
            "Share of the channel's citation partners that are mutual: it cites them and they cite it (Garlaschelli "
            "& Loffredo 2004); empty for a channel without partners or one that is only cited.",
        ),
    ),
    "statistics": (
        (
            r"group",
            "The family of statistics the row belongs to: Size, Transitivity & paths, Cohesion, Component structure, "
            "Degree correlation, Centralisation, Content or Homophily.",
        ),
        (
            r"statistic",
            "The whole-network statistic of the row, named as on the Network statistics page; † = computed on the "
            "largest weakly connected component, ‡ = on the largest strongly connected one.",
        ),
        (r"value", "The statistic's value on the network of the row's period."),
        (
            r"z_vs_.+",
            "z-score of the statistic against the baseline the column is named after: (observed − mean of the "
            "baseline's random draws) / their SD; “held fixed” when the baseline keeps the statistic by construction.",
        ),
        (
            r"p_vs_.+",
            "Two-sided p-value of the statistic against that baseline: the share of its random draws at least as "
            "extreme as the observed value (add-one corrected).",
        ),
    ),
    "modularity": (
        (
            r"modularity",
            "Modularity Q of the method's partition: the share of the tie weight inside communities beyond what the "
            "channels' strengths give by chance.",
        ),
        (
            r"modularity_z",
            "z-score of Q against the best modularity found on random graphs keeping every channel's in- and "
            "out-strength; given for the methods that maximise modularity (Leiden, Leiden directed, Louvain).",
        ),
        (
            r"p_vs_random_graphs",
            "Share of those random graphs whose best modularity reaches the observed Q (one-sided, add-one corrected).",
        ),
        (r"inter_community_ratio", "Share of the ties that join channels of two different communities."),
        (
            r"mean_e_i_index",
            "Mean E-I index of the method's communities, each weighted by its number of ties: −1 = every tie "
            "inside a community, +1 = every tie across.",
        ),
    ),
    "partition_comparison": (
        (
            r"index",
            "The index comparing the two partitions: Adjusted Rand Index (ARI), Adjusted Mutual Information (AMI), "
            "Normalised Mutual Information (NMI) or Variation of Information (VI, in bits).",
        ),
        (
            r"value",
            "The index between the two methods' partitions: 1 = identical for ARI, AMI and NMI; 0 = identical for "
            "VI, a distance.",
        ),
    ),
    "homophily": (
        (r"ties", "Ties between two channels that both hold a label of the group (self-citations left out)."),
        (r"citations", "Citations (forwards, mentions and copies counted as citations) behind those ties."),
        (r"z_(ties|citations)", "z-score of the assortativity against the random relabellings: (r − null mean) / SD."),
        (
            r"p_(ties|citations)",
            "Two-sided p-value of the assortativity: the share of random relabellings at least as extreme "
            "(add-one corrected).",
        ),
        (r"z_e_i", "z-score of the E-I index against the random relabellings."),
        (
            r"p_e_i",
            "Two-sided p-value of the E-I index: the share of random relabellings at least as extreme "
            "(add-one corrected).",
        ),
    ),
    "homophily_labels": (
        (r"label", "The label the row describes, a label of the group in the Group column."),
        (r"channels", "Observed channels holding the label."),
        (
            r"p_out",
            "Two-sided p-value of the internal share of sent ties against random relabellings (add-one corrected).",
        ),
        (r"q_out", "Benjamini–Hochberg q-value of that p, over the labels of the group and both directions."),
        (
            r"p_in",
            "Two-sided p-value of the internal share of received ties against random relabellings (add-one corrected).",
        ),
        (r"q_in", "Benjamini–Hochberg q-value of that p, over the labels of the group and both directions."),
    ),
    "label_flows": (
        (r"ties", "Ties from a channel of the citing label to a channel of the cited label."),
        (r"citations", "Citations behind those ties: forwards, mentions and copies counted as citations."),
        (r"ratio", "Observed ties over expected ties: above 1, the citing label cites the cited one more than chance."),
        (r"z", "z-score of the observed ties against the random relabellings; given for the cells tested."),
        (
            r"p",
            "Two-sided p-value of the observed ties: the share of random relabellings at least as extreme (add-one "
            "corrected); given for the cells with enough ties, observed or expected.",
        ),
        (r"q", "Benjamini–Hochberg q-value of that p, over the cells tested in the label group."),
    ),
    "mrqap_models": (
        (
            r"dependent",
            "Dependent variable of the model: “Tie (0/1)”, a linear probability model, or “log(1 + citations)”.",
        ),
        (r"r2?", "R² of the model: the share of the dependent variable's variance the predictors explain."),
        (r"mean", "Mean of the dependent variable over the ordered pairs: for the tie model, the density."),
    ),
    "mrqap_coefficients": (
        (r"dependent", "Dependent variable of the model the coefficient belongs to."),
        (
            r"predictor",
            "The dyadic predictor: same label in a label group, reverse tie (the cited channel cites back), or the "
            "sender's or receiver's activity (log messages) or audience (log subscribers).",
        ),
        (
            r"p",
            "MRQAP p-value by double semi-partialling (Dekker, Krackhardt & Snijders 2007): the share of channel "
            "relabellings whose t is at least as extreme (two-sided, add-one corrected).",
        ),
    ),
    "communities": (
        (r"channels", "Number of channels in the community."),
        (
            r"reciprocity",
            "Share of the ties inside the community that are returned (channels that are only cited left out).",
        ),
    ),
    "robustness_summary": (
        (
            r"r",
            "R-index of the attack (Schneider et al. 2011): the mean residual size over the whole removal sequence; "
            "the lower, the more the strategy damages the network.",
        ),
        (r"z", "z-score of R against the random networks: (R − their mean) / their SD."),
        (
            r"p",
            "Two-sided p-value of R: the share of random networks whose R is at least as extreme (add-one corrected).",
        ),
        (r"q", "Benjamini–Hochberg q-value of that p, over every strategy and measure of the table."),
    ),
    "robustness_curves": (
        (r"random_mean", "Mean residual size of the random networks at the same share removed."),
        (r"random_sd", "Standard deviation of the random networks' residual size at the same share removed."),
    ),
    "ban_waves": (
        (
            r"community",
            "The community removed at once: its number for an algorithmic method, the label for a label group.",
        ),
        (r"channels", "Channels in the community, all removed at once."),
        (r"share_of_the_network", "The community's share of the network's channels: the share removed."),
        (r"residual_size", "Size of what remains once the community is removed, as a share of the intact network."),
    ),
    "modular": (
        (
            r"ratio",
            "Ties still standing inside communities over ties still standing between them (a count ratio, not an "
            "observed-to-expected one); empty once no tie between communities remains.",
        ),
    ),
    "ban_replay": (
        (r"share_of_the_network", "Share of the earlier period's channels that closed in the wave."),
        (r"random", "Residual size after removing as many channels at random from the earlier period's network."),
    ),
    "alpha_sensitivity": (
        (r"r", "R-index of the strategy and measure on that backbone (the mean residual size over the removals)."),
    ),
    "dominance_channels": (
        (
            r"role",
            "The channel's role: dominant (at least two satellites, dependent on none), dependent, broker (both), "
            "allied (in a validated alliance) or peripheral.",
        ),
        (r"citations_received", "Citations the channel receives from the other channels of the analysis."),
    ),
    "dominance_pairs": (
        (r"dependent", "Name of the dependent channel: the side of the pair that relies more on the other."),
        (r"dominant", "Name of the dominant channel: the side the other relies on more."),
    ),
    "dominance_hierarchy": (
        (
            r"statistic",
            "The hierarchy test or count of the row: SpringRank energy, triangle transitivity and rank consistency, "
            "each with its p-value and mean on orientation-shuffled networks, then the numbers of citations, links, "
            "pairs by relation and channels by role.",
        ),
        (r"value", "Its value on the network of the row's period."),
    ),
    "event_effects": (
        (r"type", "The event's type, as recorded with the event."),
        (r"scope", "The labels the event is scoped to, or “whole network” for an event without a scope."),
    ),
    "links_sites": (
        (r"channels", "Channels with at least one message linking to the site."),
        (r"labels", "Per label group, the labels whose channels link to the site most, with their message counts."),
    ),
    "links_categories": (
        (r"category", "The category of sites; “Uncategorised” gathers the sites without one."),
        (
            r"role",
            "The category's role in the link shares: monetisation, mainstream or alternative; empty for a category "
            "without one.",
        ),
        (r"share", "The category's share of all links."),
        (r"channels", "Channels linking to at least one site of the category."),
        (r"sites", "Different sites of the category the channels link to."),
    ),
    "links_colinking": (
        (r"label_a", f"The primary-group label {_FIRST_OF_PAIR}."),
        (r"label_b", f"The primary-group label {_SECOND_OF_PAIR}."),
        (
            r"p",
            "p-value of sharing at least that many sites under the bipartite configuration model, where every channel "
            "keeps its number of sites and every site its number of channels.",
        ),
        (r"q", "Benjamini–Hochberg q-value: that p corrected for every pair of linking channels."),
    ),
    "links_channel_sites": ((r"messages", "Messages of the channel linking to the site."),),
    "audience_summary": (
        (
            r"figure",
            "The headline figure of the row: the scope and coverage of the comments, then the main figures of each "
            "Audience section (participation, breadth, overlap, retention, channels commenting).",
        ),
        (r"value", "Its value for the row's period; shares are fractions from 0 to 1."),
    ),
    "audience_participation": (
        (
            r"label",
            "The channel's label in the primary label group as of today (else its most recent one); empty when the "
            "channel holds no label of that group directly.",
        ),
        (r"commenters", "Different accounts replying under the channel's posts."),
        (r"replies", "Replies those accounts wrote under the channel's posts."),
        (
            r"top_?10(_pct)?_share",
            "Share of the channel's replies written by its most active 10% of commenters; empty under 20 commenters.",
        ),
        (
            r"gini",
            "Gini coefficient of the replies per account: 0 = every account writes as much, 1 = one account writes "
            "everything; empty under 20 commenters.",
        ),
        (
            r"effective_commenters",
            "Effective number of commenters: 1 / Σ sᵢ², sᵢ being each account's share of the channel's replies "
            "(Laakso & Taagepera 1979); empty under 20 commenters.",
        ),
        (
            r"hyperactive_reply_share",
            "Share of the channel's replies written by hyperactive accounts: those above the upper fence of the "
            "adjusted boxplot of replies per account, over every channel in scope.",
        ),
    ),
    "audience_activity": (
        (r"accounts", "Commenting accounts in the class."),
        (r"replies", "Replies written by the accounts of the class."),
    ),
    "audience_breadth_labels": (
        (r"label", "The label the row describes, a label of the group in the Label group column."),
        (r"commenters", "Different accounts replying under the posts of the label's channels."),
        (r"replies", "Replies written under the posts of the label's channels."),
    ),
    "audience_breadth_classes": ((r"accounts", "Accounts in the class (accounts with a single reply are left out)."),),
    "audience_overlap_pairs": (
        (r"shared", "Accounts commenting on both channels."),
        (r"ratio", "Shared commenters over expected: above 1, the two channels share more commenters than chance."),
        (r"p", _PAIR_COMMENTERS_P),
        (r"q", _BH_PAIRS),
    ),
    "audience_overlap_channels": (
        (r"label", "The channel's label in the primary label group."),
        (r"commenters", "Different accounts replying under the channel's posts."),
    ),
    "audience_overlap_labels": (
        (r"label_a", "The first label of the pair."),
        (r"label_b", "The second label of the pair."),
        (r"shared", "Accounts commenting under channels of both labels."),
        (
            r"expected",
            "Shared commenters expected by chance, every account keeping the number of labels it comments under.",
        ),
        (r"ratio", "Shared commenters over expected: above 1, the two labels share more commenters than chance."),
        (
            r"p",
            "p-value of sharing at least that many commenters by chance, every account keeping the number of labels "
            "it comments under.",
        ),
        (r"q", "Benjamini–Hochberg q-value: the p-value corrected for the number of label pairs tested."),
    ),
    "audience_cohorts": (
        (r"accounts", "Accounts in the cohort: those whose first reply falls in that quarter."),
        (
            r"\d+",
            "Share of the cohort replying again in the quarter that many quarters after its first reply; empty for "
            "a quarter not over yet.",
        ),
    ),
    "audience_channel_commenters": (
        (r"channel_id", "Pulpit's id of the channel whose posts were commented on."),
        (r"channel", "Name of the channel whose posts were commented on."),
    ),
    "near_copies": (
        (r"copy_channel", _COPY_CHANNEL),
        (r"copy_channel_id", _COPY_CHANNEL_ID),
        (r"copy_message_id", "Pulpit's id of the copying message, the later of the two."),
        (r"copy_date", "When the copying message was posted (ISO 8601)."),
        (r"origin_channel", _ORIGIN_CHANNEL),
        (r"origin_channel_id", _ORIGIN_CHANNEL_ID),
        (r"origin_message_id", "Pulpit's id of the earliest message in scope with near-identical text."),
        (r"origin_date", "When that earlier message was posted (ISO 8601)."),
        (r"lag_hours", "Hours between the two messages."),
        (r"similarity", "Jaccard resemblance of the two messages' word-shingle sets, from the threshold up to 1."),
        (r"copy_tokens", "Words of the copying message after normalisation."),
        (r"origin_tokens", "Words of the earlier message after normalisation."),
        (
            r"cluster_size",
            "Messages in scope with near-identical text, chained: a text many channels share is more likely a common "
            "quotation than a copy of one post.",
        ),
        (r"self_copy", _SELF_COPY),
    ),
    "image_copies": (
        (r"copy_channel", _COPY_CHANNEL),
        (r"copy_channel_id", _COPY_CHANNEL_ID),
        (r"copy_message_id", "Pulpit's id of the copying post's first message (an album is one post)."),
        (r"copy_date", "When the copying post was published (ISO 8601)."),
        (r"origin_channel", _ORIGIN_CHANNEL),
        (r"origin_channel_id", _ORIGIN_CHANNEL_ID),
        (r"origin_message_id", "Pulpit's id of the first message of the earliest post in scope showing the image."),
        (r"origin_date", "When that earlier post was published (ISO 8601)."),
        (r"lag_hours", "Hours between the two posts."),
        (
            r"distance",
            "Hamming distance between the two images' perceptual hashes: 0 = the same Telegram photo or an identical "
            "hash.",
        ),
        (
            r"cluster_size",
            "Posts in scope showing the image, chained: a picture many channels post is more likely a common meme "
            "than a copy of one post.",
        ),
        (r"self_copy", _SELF_COPY),
    ),
    "dyads_actors": (
        (r"id", "Pulpit's id of the channel: the id every file of the export uses."),
        (r"title", "The channel's name: its title on Telegram."),
        (r"url", "The channel's Telegram address."),
        (r"observed", "1 when the channel's own messages were read; 0 for a channel that is only cited."),
        (r"dead_leaf", "1 for a channel that is only cited (its own citations are unknown), else 0."),
        (r"messages", "Messages the channel posted inside the analysed period."),
        (r"activity_period", "The channel's first and last month with a message."),
        (r"is_lost", "1 when the channel no longer exists on Telegram, else 0."),
        (r"type", "The channel's Telegram type: channel, group, user account or bot."),
        (
            r"environment_depth",
            "Citation distance from the in-target channels: 0 in target, k for a channel of the environment "
            "reached at distance k, 1 for a channel that is only cited.",
        ),
        (r"subscribers", "Subscribers of the channel when it was last crawled."),
        (r".+", "The channel's label in the label group the column is named after; empty when it holds none."),
    ),
    "dyads_edgelist": (
        (r"sender", _SENDER),
        (r"receiver", _RECEIVER),
        (r"citations", "Citations behind the tie: forwards + mentions + copies + image copies."),
        (r"forwards", "Forwards of the receiver's posts by the sender."),
        (r"mentions", "Messages of the sender mentioning the receiver (t.me links and @handles)."),
        (r"copies", "Near-copies of the receiver's text by the sender (0 unless near-copies counted as ties)."),
        (
            r"image_copies",
            "Image copies of the receiver's posts by the sender (0 unless image copies counted as ties).",
        ),
        (r"weight", "Weight of the tie under the run's tie-weight strategy, before any rescaling for the maps."),
    ),
    "dyads_events": (
        (r"sender", _SENDER),
        (r"receiver", _RECEIVER),
        (r"timestamp", "When the citing message was posted, in UTC (ISO 8601)."),
        (r"type", "The kind of citation: forward, mention, copy (near-copy of text) or image_copy."),
        (r"message_id", "Pulpit's id of the citing message (for an image copy, of its post's first message)."),
    ),
    "dyads_dyads": (
        (r"sender", "Pulpit's id of the first channel of the ordered pair: the potential citer."),
        (r"receiver", "Pulpit's id of the second channel of the ordered pair: the potentially cited one."),
        (r"tie", "1 when the sender cites the receiver, else 0: the dependent variable of the tie model."),
        (
            r"log_citations",
            "log(1 + citations of the receiver by the sender): the dependent variable of the volume model.",
        ),
        (r"same_labelgroup\d+", "1 when the two channels hold the same label in the label group of that id, else 0."),
        (r"reverse_tie", "1 when the receiver cites the sender, else 0: the reciprocity control."),
        (r"sender_activity", "log(1 + messages of the sender in the analysed period)."),
        (r"receiver_activity", "log(1 + messages of the receiver in the analysed period)."),
        (r"sender_audience", "log(1 + subscribers of the sender)."),
        (r"receiver_audience", "log(1 + subscribers of the receiver)."),
    ),
    "dyads_presence": (
        (r"actor", "Pulpit's id of the channel."),
        (r".+", "1 when the channel is part of the network of the period the column is named after, else 0."),
    ),
    "dyads_wave": (
        (r"actor", "Pulpit's id of the citing channel of the row."),
        (
            r".+",
            "One column per channel, named by its id: 1 when the row's channel cites it in that period, else 0.",
        ),
    ),
}

# Tables whose columns after the first few are one per channel or per period: the dictionary lists the leading
# columns, then one line for the rest. table → (leading columns, name of the line, its meaning).
_REPEATED_COLUMNS: dict[str, tuple[int, str, str]] = {
    "dyads_presence": (
        1,
        "<period>",
        "One column per timeline period, named by its key: 1 when the channel is part of that period's network, else 0.",
    ),
    "dyads_wave": (
        1,
        "<channel id>",
        "One column per channel, named by its id: 1 when the row's channel cites it in that period, else 0.",
    ),
}
# dyads/actors.csv: id, title, url, then one column per label group, then these eight.
_ACTORS_LEADING = 3
_ACTORS_TRAILING = 8

_LABEL_GROUP_COLUMN = (
    "The channel's label in the label group “{name}”: the one it held longest inside the analysed period."
)
_COMMUNITY_COLUMN = (
    "The number of the channel's community under the grouping method “{name}” (the community table lists the "
    "communities of each method)."
)
_MATRIX_LABEL = "The label of the row, a label of the label group the sheet is named after."
_MATRIX_TOTAL = "Links of the label's channels, every category together."
_MATRIX_CATEGORY = "Links of the label's channels to sites of the category the column is named after."

# Column descriptions, keyed by the column's snake_case form (:func:`column_key`): a spreadsheet's "In-strength" and
# a CSV's in_strength share one entry. Shares are fractions from 0 to 1 (spreadsheets show them as percentages).
# A key that means something else in one table is described there (TABLE_COLUMNS).
COLUMNS: dict[str, str] = {
    # Identity of a channel, a period, a label
    "period": (
        "The timeline period of the row, by its key (2024, 2024Q1, 2024-03; a sliding window is named after the "
        "step it ends with); “All periods” is the whole range of the analysis."
    ),
    "channel_id": "Pulpit's id of the channel, the same in every file of the export.",
    "channel": "The channel's name: its title on Telegram.",
    "channel_telegram_id": "The channel's numeric id on Telegram, as Telegram assigns it.",
    "channel_username": "The channel's Telegram username; empty when it has none.",
    "channel_title": "The channel's name: its title on Telegram.",
    "url": "The channel's Telegram address.",
    "label": "The channel's label in the primary label group.",
    "label_group": "The label group the labels of the row belong to.",
    "group": "The label group the row describes.",
    "label_a": "Label of the first channel, or the first label, of the pair.",
    "label_b": "Label of the second channel, or the second label, of the pair.",
    "channel_a_id": f"Pulpit's id {_FIRST_OF_PAIR}.",
    "channel_a": f"Name {_FIRST_OF_PAIR}.",
    "channel_b_id": f"Pulpit's id {_SECOND_OF_PAIR}.",
    "channel_b": f"Name {_SECOND_OF_PAIR}.",
    "environment_depth": (
        "Citation distance from the in-target channels: 0 for an in-target channel, k for a channel of the "
        "environment reached at distance k, 1 for a channel that is only cited."
    ),
    "subscribers": "Subscribers of the channel when it was last crawled.",
    "messages": "Messages the channel posted inside the analysed period.",
    "activity_start": "First month with a message of the channel (YYYY-MM).",
    "activity_end": "Last month with a message of the channel (YYYY-MM).",
    # Channel measures
    "in_strength": "Weighted in-degree: the total weight of the ties the channel receives.",
    "out_strength": "Weighted out-degree: the total weight of the ties the channel sends.",
    "pagerank": (
        "PageRank: the probability that a random walk along the citation ties is at the channel; high when "
        "well-cited channels cite it (Brin & Page 1998)."
    ),
    "hits_hub": "HITS hub score: high when the channel cites good authorities (Kleinberg 1999).",
    "hits_authority": "HITS authority score: high when good hubs cite the channel (Kleinberg 1999).",
    "in_degree_centrality": "Distinct channels citing this one, divided by the channels that could (n − 1); unweighted.",
    "out_degree_centrality": "Distinct channels this one cites, divided by the channels it could (n − 1); unweighted.",
    "burt_s_constraint": "Burt's constraint: low for a broker spanning structural holes, high inside a closed group (Burt 1992).",
    "local_clustering": "Directed local clustering coefficient: how far the channel's neighbours cite each other (Fagiolo 2007).",
    "reciprocity": "Share of the channel's citation partners that are mutual: it cites them and they cite it.",
    "amplification_factor": "Forwards the channel received from in-target channels, per message it posted.",
    "content_originality": "Share of the channel's messages that are not forwards.",
    "visual_originality": "Share of the channel's picture posts that do not re-post another channel's earlier image.",
    "david_s_score": "David's score of dominance, corrected for sparse pairs (de Vries et al. 2006); higher = more dominant.",
    "normalised_david_s_score": "David's score rescaled to run from 0 to n − 1, n being the number of ranked channels.",
    "linking_posts_share": "Share of the channel's messages carrying a web link.",
    "distinct_sites": "Different web sites the channel links to.",
    "platform_diversity": "Effective number of site categories the channel links to (Hill number of order 2), over its categorised links.",
    "monetisation_link_share": "Share of the channel's links pointing to donation, crowdfunding or shop sites.",
    "mainstream_link_share": "Share of the channel's links pointing to mainstream platforms.",
    "alternative_link_share": "Share of the channel's links pointing to alternative platforms.",
    # edges.csv
    "source_id": "Pulpit's id of the citing channel (channel_id in nodes.csv).",
    "source": "Name of the citing channel.",
    "target_id": "Pulpit's id of the cited channel.",
    "target": "Name of the cited channel.",
    "weight": "Weight of the tie under the run's tie-weight strategy (see the Methods record).",
    "weight_forwards": "Forwards of the cited channel's posts by the citing channel.",
    "weight_mentions": "Messages of the citing channel mentioning the cited one (t.me links and @handles).",
    "weight_copies": "Near-copies of the cited channel's text by the citing channel (0 unless near-copies counted as ties).",
    "weight_image_copies": "Image copies of the cited channel's posts by the citing channel (0 unless image copies counted as ties).",
    # Network statistics, modularity, partition comparison
    "statistic": "Name of the statistic the row reports; its value is in the Value column.",
    "value": "Value of what the row's first columns name: a statistic, an index or a figure.",
    "method": "The grouping method: a community detection algorithm, or a label group (marked “(label group)”).",
    "method_a": "The first of the two grouping methods compared.",
    "method_b": "The second of the two grouping methods compared.",
    "index": "The partition-comparison index of the row: ARI, AMI, NMI or VI.",
    "modularity": "Modularity of the method's partition: how much more the ties stay inside communities than chance.",
    "modularity_z": "z-score of the modularity against the best modularity of random graphs with the same tie strengths.",
    "p_vs_random_graphs": "Share of those random graphs whose best modularity reaches the observed one.",
    "inter_community_ratio": "Share of the ties that join channels of two different communities.",
    "mean_e_i_index": "Mean E-I index of the communities, weighted by their ties: −1 closed, +1 open.",
    # Communities
    "community": "The community: its number for an algorithmic method, the label for a label group.",
    "colour": "The community's colour on the map, as a hexadecimal code.",
    "channels": "Number of channels the row covers.",
    "internal_ties": "Ties between two channels of the community.",
    "external_ties": "Ties joining a channel of the community and a channel outside it, in either direction.",
    "e_i_index": "E-I index: (external − internal) / (external + internal) ties; −1 = closed, +1 = open (Krackhardt & Stern 1988).",
    "internal_density": "Share of the possible directed ties between the community's channels that exist.",
    "mean_clustering": "Mean local clustering coefficient of the community's channels.",
    "mean_path_length": "Mean shortest path, direction ignored, in the community's largest connected part.",
    "diameter": "Longest shortest path, direction ignored, in the community's largest connected part.",
    "modularity_contribution": "The community's part of the method's modularity: the parts of a method's communities add up to it.",
    "members": "Names of the community's channels, separated by commas.",
    # Homophily and label flows
    "labelled_channels": "Observed channels holding a label of the group.",
    "ties": "Number of ties between the channels the row covers.",
    "citations": "Citations behind those ties: forwards, mentions and copies counted as citations.",
    "assortativity_r_ties": "Nominal assortativity of the ties: 1 = every tie inside its label, 0 = labels unrelated to who cites whom (Newman 2003).",
    "assortativity_r_citations": "Nominal assortativity with every citation counted, instead of every tie once.",
    "null_mean_ties": "Mean assortativity of the ties over random relabellings of the same channels.",
    "null_mean_citations": "Mean assortativity of the citations over random relabellings of the same channels.",
    "e_i_index_labelled_ties": "E-I index over the ties between labelled channels: −1 = all inside a label, +1 = all across labels.",
    "expected_e_i": "Mean of that E-I index over random relabellings of the same channels.",
    "baseline_share_w": "Share of the other labelled channels holding the label: the share of its ties that would stay inside it by chance.",
    "internal_share_of_sent_ties": "Share of the ties sent by the label's channels that go to a channel of the same label.",
    "internal_share_of_received_ties": "Share of the ties received by the label's channels that come from a channel of the same label.",
    "inbreeding_homophily_out": "Inbreeding homophily of the sent ties: (internal share − w) / (1 − w); 0 = chance, 1 = only inside (Coleman 1958).",
    "inbreeding_homophily_in": "Inbreeding homophily of the received ties: (internal share − w) / (1 − w); 0 = chance, 1 = only inside.",
    "net_exporter_ties": "Ties received from other labels minus ties sent to them, over their sum: positive when the label is cited more than it cites.",
    "net_exporter_citations": "Citations received from other labels minus citations made to them, over their sum.",
    "out_of_scope_share_ties": "Share of the ties sent by the label's channels that go to channels without a label of the group, or outside the observed network.",
    "out_of_scope_share_citations": "Share of the citations made by the label's channels that go to such channels.",
    "ties_sent": "Ties from the label's channels to labelled channels, the label's own included.",
    "ties_received": "Ties to the label's channels from labelled channels, the label's own included.",
    "citations_sent": "Citations the label's channels make of labelled channels.",
    "citations_received": "Citations the label's channels receive from labelled channels.",
    "citing_label": "The label held by the citing channels of the row, in the row's label group.",
    "cited_label": "The label held by the cited channels of the row, in the row's label group.",
    "expected_ties": "Mean number of those ties over random relabellings of the same channels.",
    "expected_citations": "Mean number of those citations over random relabellings of the same channels.",
    "ratio": "The observed count over the count expected by chance.",
    # Dyadic regression
    "dependent": "Dependent variable of the model: a tie (0/1, linear probability model) or log(1 + citations).",
    "predictor": "The dyadic predictor the coefficient belongs to.",
    "coefficient": "OLS coefficient of the predictor, the other predictors held fixed.",
    "standardised_β": "Standardised coefficient β, in standard deviations of predictor and outcome: comparable across predictors.",
    "t": "OLS t-statistic of the coefficient (its ordinary p-value is not valid for dyadic data: read the permutation p).",
    "mean": "Mean of the dependent variable over the ordered pairs.",
    "intercept": "Intercept of the model: its prediction when every predictor is zero.",
    "actors": "Channels in the model: the observed channels holding a label in every label group used.",
    "dyads": "Ordered pairs of those channels: the observations of the model.",
    "permutations": "Random relabellings of the channels behind each p-value.",
    # Dominance
    "role": "The role assigned to the row: a channel's dominance role, or a site category's role in the link shares.",
    "david_rank": "The channel's rank by David's score, 1 = most dominant.",
    "springrank": "SpringRank score: the channel's position in the hierarchy that best fits the pairs (De Bacco et al. 2018).",
    "springrank_rank": "The channel's rank by SpringRank, 1 = highest.",
    "citations_made": "Citations the channel makes of the other channels of the analysis.",
    "partners": "Channels it exchanges enough citations with to enter the ranking (at least the minimum number of events).",
    "supplies_sum_of_content_shares": "Sum of the dependences its partners place on it: the share of each citer's citing going to it, plus its share of the citations each channel it cites receives.",
    "satellites": "Partners that clearly depend on the channel: for at least half of their citing, or of the citations they receive.",
    "relies_max_content_share": "The channel's largest dependence on one partner (content or reach share), in the pairs where it is clearly the dependent side; empty when there is none.",
    "reach_concentration": "Share of the citations the channel receives that come from its largest citer.",
    "validated_dependents": "Channels citing this one more than chance (statistically validated links).",
    "validated_sources": "Channels this one cites more than chance (statistically validated links).",
    "dependent_id": "Pulpit's id of the dependent channel of the pair.",
    "dependent_label": "The primary-group label of the dependent channel.",
    "dominant_id": "Pulpit's id of the dominant channel of the pair.",
    "dominant": "Name of the dominant channel of the pair.",
    "dominant_label": "The primary-group label of the dominant channel.",
    "relation": "Alliance (both directions validated), dependence (one direction) or unvalidated (neither).",
    "mutual": "1 when each of the two channels cites the other, 0 when only one does.",
    "dependent_to_dominant_citations": "Citations of the dominant channel by the dependent one.",
    "dependent_content_share": "Share of the dependent's citing messages that cite the dominant channel; empty when the dependent cites too little.",
    "dominant_reach_share": "Share of the citations the dominant receives that come from the dependent.",
    "dependent_to_dominant_p": "Hypergeometric p-value of the dependent → dominant link: that many citations or more by chance (Tumminello et al. 2011); empty below the minimum number of events.",
    "dependent_to_dominant_q": "Benjamini–Hochberg q-value of that p, over every link tested.",
    "dominant_to_dependent_citations": "Citations of the dependent channel by the dominant one.",
    "dominant_content_share": "Share of the dominant's citing messages that cite the dependent channel; empty when the dominant cites too little.",
    "dependent_reach_share": "Share of the citations the dependent receives that come from the dominant.",
    "dominant_to_dependent_p": "Hypergeometric p-value of the dominant → dependent link; empty below the minimum number of events.",
    "dominant_to_dependent_q": "Benjamini–Hochberg q-value of that p, over every link tested.",
    "dependence_of_dependent": "The dependent's dependence on the dominant: the mean of its content share and its reach share.",
    "dependence_of_dominant": "The dominant's dependence on the dependent: the mean of its content share and its reach share.",
    "net_balance": "Dependence of the dependent minus dependence of the dominant.",
    "asymmetry": "Net balance over the larger of the two dependences: 0 = balanced, 1 = one-way.",
    # Event impact
    "event_date": "Date of the event (YYYY-MM-DD).",
    "event": "The event's subject, as recorded.",
    "type": "The kind of thing the row records, as the analysis names it: an event's type, a citation's kind.",
    "scope": "The labels the event is scoped to, or “whole network”.",
    "design": "The model fitted: a segmented regression of the whole network, or a comparison of the scoped labels with the rest.",
    "metric": "The weekly metric the effect is measured on.",
    "unit": "How the metric is modelled: “log(1 + count)” for counts, “share” for shares.",
    "weeks_before": "Weeks with data before the event's week, inside the window.",
    "weeks_after": "Weeks with data from the event's week on, inside the window.",
    "level_change": "Jump of the metric at the event's week (for counts on log(1 + count): 0.1 is about +10%).",
    "level_change_pct": "The level change as a percentage, (e^change − 1) × 100; given for counts.",
    "level_se": "Standard error of the level change, robust to autocorrelation (Newey–West).",
    "level_p_hac": "p-value of the level change from that standard error.",
    "level_p_placebo": "Share of the placebo weeks at which the same model finds a level change at least as large (add-one corrected).",
    "level_q": "Benjamini–Hochberg q-value of the placebo p of the level change, over every event and metric.",
    "slope_change": "Change of the metric's weekly trend from the event's week on.",
    "slope_se": "Standard error of the slope change, robust to autocorrelation (Newey–West).",
    "slope_p_hac": "p-value of the slope change from that standard error.",
    "slope_p_placebo": "Share of the placebo weeks at which the same model finds a slope change at least as large (add-one corrected).",
    "slope_q": "Benjamini–Hochberg q-value of the placebo p of the slope change, over every event and metric.",
    "placebo_dates": "Number of placebo weeks the placebo p-values compare the event with.",
    "confounded_by": "Other recorded events inside the window, whose effects mix with this one's.",
    "week": "The week, by the date of its Monday (YYYY-MM-DD).",
    "messages_posted": "Messages the observed channels posted that week.",
    "forwards_posted": "Forwards among those messages.",
    "active_channels": "Channels posting at least once that week.",
    "new_channels_first_message": "Channels posting their first message that week.",
    "in_scope_citations": "Citations between observed channels that week.",
    "imported_share_forwards_from_outside_the_scope": "Share of that week's forwards whose source is outside the observed channels.",
    "citation_concentration_herfindahl": "Herfindahl concentration of that week's citations over the cited channels: 1 = all to one channel.",
    # Outbound links
    "linking_messages": "Messages of the channel carrying at least one web link.",
    "link_events": "Links, each site counted once per message.",
    "monetisation_share": "Share of the channel's links pointing to donation, crowdfunding or shop sites.",
    "mainstream_share": "Share of the channel's links pointing to mainstream platforms.",
    "alternative_share": "Share of the channel's links pointing to alternative platforms.",
    "categorised_share": "Share of the channel's links whose site has a category.",
    "top_sites": "The sites the channel links to most, each with its number of messages.",
    "site": "The web site: its registered domain; an outlet on a hosting platform is a site of its own.",
    "category": "The category of the site; “Uncategorised” when it has none.",
    "posts": "Messages linking to the site.",
    "first_link": "Date of the first message linking to the site.",
    "last_link": "Date of the last message linking to the site.",
    "labels": "The labels of the channels the row concerns, the most frequent first.",
    "share": "The row's part of the table's total, as a fraction from 0 to 1.",
    "sites": "Number of different web sites the row covers.",
    "shared_sites": "Sites both channels link to.",
    "sites_a": "Different sites the first channel links to.",
    "sites_b": "Different sites the second channel links to.",
    "expected_shared": "Shared sites expected by chance, every channel keeping its number of sites and every site its number of channels (bipartite configuration model, Saracco et al. 2015).",
    "validated": "1 when the pair shares more sites than chance (q under the threshold), else 0.",
    "common_sites_rarest_first": "The sites both channels link to, those linked by the fewest channels first.",
    "total": "The sum of the row over every category.",
    # Audience
    "figure": "The headline figure the row reports.",
    "commenters": "Number of different accounts that wrote at least one reply.",
    "replies": "Replies written by commenting accounts.",
    "replies_per_commenter": "Mean number of replies per commenting account.",
    "commenters_per_subscriber": "Commenting accounts divided by the channel's subscribers.",
    "one_time_share": "Share of the commenting accounts that replied only once.",
    "gini": "Gini coefficient of the replies per account: 0 = every account writes as much, 1 = one account writes everything.",
    "effective_commenters": "Effective number of commenters: 1 / Σ sᵢ², sᵢ being each account's share of the replies (Laakso & Taagepera 1979).",
    "hyperactive_reply_share": "Share of the replies written by hyperactive accounts: those above the upper fence of the adjusted boxplot.",
    "commenting_elsewhere_share": "Share of the label's commenters who also comment under another label of the group.",
    "shared": "Accounts the two have in common.",
    "expected": "Shared commenters expected by chance, every account keeping the number of channels it comments on.",
    "month": "The calendar month of the row (YYYY-MM).",
    "active_commenters": "Accounts replying that month.",
    "new_commenters": "Accounts replying for the first time that month.",
    "channels_with_comments": "Channels with at least one reply that month.",
    "commenting_channel_telegram_id": "Telegram id of the channel that commented in its own name.",
    "commenting_channel": "Name of the channel that commented in its own name.",
    "commenting_in_target": "1 when the commenting channel is itself an in-target channel, else 0.",
    "comments": "Comments it wrote under the other channel's posts.",
    "first": "When it first commented there (ISO 8601).",
    "last": "When it last commented there (ISO 8601).",
    "cited_either_way": "1 when one of the two channels cites the other, 0 when neither does; empty when unknown.",
    "accounts": "Number of commenting accounts the row covers.",
    "replies_per_account": "The class of accounts, by the number of replies they wrote.",
    "share_of_accounts": "Share of all the commenting accounts that fall in the class.",
    "share_of_replies": "Share of all the replies written by the accounts of the class.",
    "channels_reached": "Mean number of channels an account of the class comments on.",
    "by_chance": "Mean number of channels those accounts would reach by chance with as many replies (rarefaction).",
    "observed_chance": "Channels reached over channels reached by chance: under 1, narrower than chance.",
    "below_chance": "Share of the class's accounts reaching fewer channels than chance would give them.",
    "exclusive": "Share of the channel's commenters who comment on no other observed channel.",
    "exclusive_by_chance": "That share expected by chance, every account keeping the number of channels it comments on.",
    "first_reply": "The quarter of the cohort's first reply.",
    # Robustness
    "strategy": "The attack strategy: the order in which the channels are removed.",
    "measure": "What is measured of the network that remains: WCC or SCC (largest weakly or strongly connected part), Reach (pairs still connected) or Strength (tie weight still held).",
    "r": "R-index: the mean residual size over the whole removal sequence.",
    "r2": "R² of the regression model: the share of the variance its predictors explain.",
    "random_r_mean": "Mean R-index of the random networks the run compares with (its null model).",
    "random_r_sd": "Standard deviation of the R-index over those random networks.",
    "critical_share": "Share of the channels removed when the residual size first falls under 5% of its starting value; empty when it never does.",
    "share_removed": "Share of the channels removed so far.",
    "residual_size": "Size of what remains, as a share of the intact network.",
    "random_mean": "Mean of the same quantity on the random networks.",
    "random_sd": "Standard deviation of the same quantity on the random networks.",
    "efficiency": "Weighted global efficiency of what remains (Latora & Marchiori 2001).",
    "share_of_the_network": "Share of the network's channels the row removes.",
    "random_residual": "Residual size after removing as many channels at random.",
    "within_communities": "Share of the ties inside communities still standing.",
    "between_communities": "Share of the ties between communities still standing.",
    "wave_period": "The period whose recorded closures are replayed.",
    "channels_before": "Channels in the network of the period before the wave.",
    "closed": "Channels of that network recorded as closed in the wave.",
    "predicted": "Residual size after removing the closed channels from the earlier period's network.",
    "random": "Residual size after removing as many channels at random.",
    "observed": "Residual size of the survivors in the period after the wave; empty when there is none.",
    "alpha": "Disparity-filter α of the backbone the attack runs on (0 = the full network).",
    "backbone_channels": "Channels left in that backbone of the network.",
    "backbone_ties": "Ties left in that backbone of the network.",
    # Generic statistics
    "z": "z-score of the observed value against the null model: (observed − null mean) / null SD.",
    "p": "p-value of the row's test: the probability, under its null model, of a value at least as extreme.",
    "q": "Benjamini–Hochberg q-value: the p-value corrected for the number of tests of the table.",
}
# (regex over the snake_case key, description) for the columns whose name carries a parameter or a label.
COLUMN_PATTERNS: tuple[tuple[str, str], ...] = (
    (r"community_.+", "The number of the channel's community under the grouping method the column is named after."),
    (r"label_.+", "The channel's label in the label group the column is named after."),
    (
        r"diffusion_lag.*",
        "Median hours between an original post and the channel's forward of it, within the window in the column's name.",
    ),
    (
        r"within_module_z.*",
        "Within-community degree z-score, for the grouping method in the column's name (Guimerà & Amaral 2005).",
    ),
    (
        r"participation_coefficient.*",
        "Participation coefficient: how evenly the channel's neighbours spread over the communities of that method.",
    ),
    (r"participation_weighted.*", "Participation coefficient computed on the tie weights instead of the neighbours."),
    (
        r"module_role.*",
        "The channel's role in its community, from its z-score and participation (Guimerà & Amaral 2005).",
    ),
    (r".*confidence.*", "Share of the SBM posterior samples that put the channel in the community reported for it."),
    (r"z_vs_.+", "z-score of the statistic against the baseline the column is named after."),
    (r"p_vs_.+", "p-value of the statistic against the baseline the column is named after."),
    (r"top_?10(_pct)?_share", "Share of the replies written by the most active 10% of the commenting accounts."),
    (r"z_(ties|citations|e_i)", "z-score of the statistic named in brackets against the random relabellings."),
    (r"p_(ties|citations|e_i)", "p-value of the statistic named in brackets against the random relabellings."),
    (r"p_(in|out)", "p-value of the label's internal share of received (in) or sent (out) ties."),
    (r"q_(in|out)", "Benjamini–Hochberg q-value of the label's internal share of received (in) or sent (out) ties."),
    (
        r"cross_label_citation_share_.+",
        "Share of that week's citations joining channels with different labels of the label group in brackets.",
    ),
    (r"standardised.*", "Standardised coefficient β, comparable across predictors."),
    (r"\d+", "Share of the cohort replying again that many quarters after its first reply."),
)


# What each sheet of each workbook holds, keyed by (workbook, sheet).
SHEETS: dict[tuple[str, str], str] = {
    ("channel_table.xlsx", "Channels"): "One row per channel: activity, ties, measures and communities.",
    ("network_table.xlsx", "Statistics"): "The whole-network statistics, with their tests against each baseline.",
    ("network_table.xlsx", "Modularity"): "Modularity of each grouping method's partition, against random graphs.",
    (
        "network_table.xlsx",
        "Partition comparison",
    ): "Agreement between every pair of grouping methods, under four indices.",
    ("network_table.xlsx", "Homophily"): "Per label group: assortativity and E-I index against random relabellings.",
    ("network_table.xlsx", "Homophily by label"): "Per label: how much of its ties stay inside it, against chance.",
    ("network_table.xlsx", "Label flows"): "Citations from label to label, observed against random relabellings.",
    ("network_table.xlsx", "MRQAP models"): "The dyadic regression models: fit and size.",
    ("network_table.xlsx", "MRQAP coefficients"): "The dyadic regression coefficients, with permutation p-values.",
    ("community_table.xlsx", "Communities"): "One row per community of every grouping method.",
    (
        "robustness_table.xlsx",
        "Summary",
    ): "Per attack strategy and measure: the R-index against random networks and the critical share.",
    (
        "robustness_table.xlsx",
        "Curves",
    ): "The residual size at each share of channels removed, with the random networks' mean and SD.",
    ("robustness_table.xlsx", "Efficiency"): "Weighted global efficiency at each share of channels removed.",
    (
        "robustness_table.xlsx",
        "Ban waves",
    ): "Removing each whole community at once, against removing as many channels at random.",
    ("robustness_table.xlsx", "Modular"): "Ties within and between communities still standing as channels are removed.",
    (
        "robustness_table.xlsx",
        "Ban replay",
    ): "Each period's recorded closures replayed on the previous period's network.",
    (
        "robustness_table.xlsx",
        "Alpha sensitivity",
    ): "The R-index on backbones of the network at several disparity-filter α.",
    ("dominance.xlsx", "Channels"): "One row per ranked channel: dominance scores, role and dependences.",
    (
        "dominance.xlsx",
        "Pairs",
    ): "One row per pair of channels with a citation between them, oriented from the dependent to the dominant.",
    ("dominance.xlsx", "Hierarchy"): "Whole-network tests of the hierarchy and the counts behind them.",
    (
        "event_impact.xlsx",
        "Effects",
    ): "One row per event and metric: level and slope change with their p- and q-values.",
    ("event_impact.xlsx", "Weekly series"): "The network's weekly metrics the effects are fitted on.",
    ("links.xlsx", "Channels"): "One row per observed channel: how much it links out and where.",
    ("links.xlsx", "Sites"): "One row per linked site.",
    ("links.xlsx", "Categories"): "One row per site category.",
    ("links.xlsx", "Co-linking"): "Pairs of channels linking to the same sites, against chance.",
    ("links.xlsx", "Channel sites"): "One row per channel and site, with the messages linking it.",
    ("links.xlsx", "Matrix"): "Links of each label of a label group to each category of site.",
    ("audience.xlsx", "Summary"): "The headline figures of every section.",
    ("audience.xlsx", "Participation"): "Per channel: how unevenly its comments are spread over its commenters.",
    ("audience.xlsx", "Activity"): "Commenting accounts by the number of replies they wrote.",
    ("audience.xlsx", "Breadth labels"): "Per label: its commenters and how many comment under other labels.",
    ("audience.xlsx", "Breadth classes"): "Channels reached by commenters, by activity, against chance.",
    ("audience.xlsx", "Overlap pairs"): "Pairs of channels sharing commenters, against chance.",
    ("audience.xlsx", "Overlap channels"): "Per channel: its commenters and how many comment nowhere else.",
    ("audience.xlsx", "Overlap labels"): "Pairs of labels sharing commenters, against chance.",
    ("audience.xlsx", "Retention by month"): "Commenters per month, and the newcomers among them.",
    ("audience.xlsx", "Cohorts"): "Each quarter's new commenters, and the share of them commenting again later.",
    (
        "audience.xlsx",
        "Channel commenters",
    ): "Comments written by channels under other channels' posts, in their own name.",
}


def describe_sheet(workbook: str, sheet: str) -> str:
    """What the sheet *sheet* of *workbook* holds; a continuation sheet (``Curves (2)``) says so."""
    original, base = _original(workbook), _sheet_base(sheet)
    description = SHEETS.get((original, base), "")
    if not description and base.startswith("Matrix"):
        description = SHEETS.get((original, "Matrix"), "")
    if description and _SHEET_CONTINUATION.search(sheet):
        description = f"{description.rstrip('.')} (the table continues from the sheet before)."
    return description


def _prefixed(header: str, prefix: str) -> str | None:
    """The name after *prefix* in a channel-table header (``Label: Nation`` → ``Nation``), else ``None``."""
    text = str(header).strip()
    return text[len(prefix) :].strip() if text.startswith(prefix) and len(text) > len(prefix) else None


def _matrix_column(key: str, sheet: str, position: int | None, count: int | None) -> str:
    """A column of a ``Matrix <label group>`` sheet: the label, then one column per category, then the total.

    By position when it is known; else the label column is recognised by the sheet's title, which is cut to
    Excel's 31 characters.
    """
    if position is not None:
        if position == 0:
            return _MATRIX_LABEL
        if key == "total" and (count is None or position == count - 1):
            return _MATRIX_TOTAL
        return _MATRIX_CATEGORY
    title = column_key(_sheet_base(sheet)[len("Matrix") :])
    if title and (key == title or (len(sheet) >= 28 and key.startswith(title))):
        return _MATRIX_LABEL
    return _MATRIX_TOTAL if key == "total" else _MATRIX_CATEGORY


def describe_column(
    header: str, workbook: str = "", sheet: str = "", position: int | None = None, count: int | None = None
) -> str:
    """What the column *header* holds, ``""`` for one the dictionary does not know.

    *workbook* (the file's name, a CSV's too) and *sheet* say which table the column stands in: a column is
    described there first (:data:`TABLE_COLUMNS`), then in general. *position* (0-based) and *count* (the
    table's number of columns) settle the tables read by position: a ``Matrix`` sheet, ``dyads/actors.csv``.
    """
    key = column_key(header)
    table = table_of(workbook, sheet) if workbook else ""
    if table == "links_matrix":
        return _matrix_column(key, sheet, position, count)
    # The channel table names its label and community columns after the analyst's label groups and the methods:
    # they are described by that prefix, whatever the name after it ("Label: Group", "Label: A").
    for prefix, template in (("Label:", _LABEL_GROUP_COLUMN), ("Community:", _COMMUNITY_COLUMN)):
        name = _prefixed(header, prefix)
        if name is not None:
            return template.format(name=name)
    if table == "dyads_actors" and position is not None and count is not None:
        if _ACTORS_LEADING <= position < count - _ACTORS_TRAILING:
            return TABLE_COLUMNS[table][-1][1]
    for pattern, description in TABLE_COLUMNS.get(table, ()):
        if re.fullmatch(pattern, key):
            return description
    if key in COLUMNS:
        return COLUMNS[key]
    for pattern, description in COLUMN_PATTERNS:
        if re.fullmatch(pattern, key):
            return description
    return ""


def _read_columns(root: str, name: str) -> list[tuple[str, list[str]]]:
    members = family_members(root, name)
    path = os.path.join(root, members[0] if members else name)
    if name.endswith(".csv"):
        with open(path, newline="", encoding="utf-8-sig") as f:
            header = next(csv.reader(f), [])
        return [("", header)]
    if name.endswith(".xlsx"):
        import openpyxl

        workbook = openpyxl.load_workbook(path, read_only=True)
        try:
            out = []
            for sheet in workbook.worksheets:
                if sheet.title == ABOUT_SHEET:
                    continue
                first = next(sheet.iter_rows(min_row=1, max_row=1, values_only=True), ())
                out.append((sheet.title, [str(h) for h in first if h is not None]))
            return out
        finally:
            workbook.close()
    return []


def columns_of(root: str, name: str) -> list[tuple[str, list[str]]]:
    """``(sheet, headers)`` of a CSV (one entry, sheet ``""``) or of every table sheet of a workbook.

    For the row of a family of files, the columns of its first file. ``[]`` for a file that cannot be read:
    reading never raises.
    """
    try:
        return _read_columns(root, name)
    except Exception as exc:  # whatever the file holds, the dictionary goes on
        logger.warning("Data dictionary: could not read the columns of %s: %s", name, exc)
        return []


# ── Writing ──────────────────────────────────────────────────────────────────


def _described(headers: list[str], name: str, sheet: str) -> list[tuple[str, str]]:
    """``(header, meaning)`` of a table's columns; the per-channel or per-period columns of a matrix as one line."""
    repeated = _REPEATED_COLUMNS.get(table_of(name, sheet))
    listed = headers[: repeated[0]] if repeated else headers
    columns = [(h, describe_column(h, name, sheet, position=i, count=len(headers))) for i, h in enumerate(listed)]
    if repeated and len(headers) > repeated[0]:
        columns.append((repeated[1], repeated[2]))
    return columns


def dictionary(root: str, names: list[str]) -> list[dict[str, Any]]:
    """Every listed file with its description and, for tables, its sheets' columns and their meaning.

    A table that cannot be read keeps its entry, its description ending with :data:`UNREADABLE_NOTE`.
    """
    entries = []
    for group, files in file_groups(root, names):
        for name in files:
            description = describe_file(name, root)
            sheets = []
            if has_columns(root, name):
                try:
                    tables = _read_columns(root, name)
                except Exception as exc:  # an unreadable file must not abort the export
                    logger.warning("Data dictionary: could not read the columns of %s: %s", name, exc)
                    description = f"{description} {UNREADABLE_NOTE}".strip()
                else:
                    sheets = [
                        {
                            "sheet": sheet,
                            "description": describe_sheet(name, sheet) if sheet else "",
                            "columns": _described(headers, name, sheet),
                        }
                        for sheet, headers in tables
                    ]
            entries.append(
                {
                    "name": name,
                    "group": group,
                    "anchor": anchor(name),
                    "description": description,
                    "sheets": sheets,
                }
            )
    return entries


def _md_text(text: object) -> str:
    """*text* as plain Markdown text of one line, safe inside a table cell: ``|`` and backticks escaped, a ``<``
    that would open a tag too."""
    folded = " ".join(str(text).split())
    folded = folded.replace("\\", "\\\\").replace("|", "\\|").replace("`", "\\`")
    return re.sub(r"<(?=[A-Za-z/!?])", r"\\<", folded)


def _md_code(text: object) -> str:
    """*text* as a Markdown code span of one line, safe inside a table cell whatever it holds."""
    folded = " ".join(str(text).split())
    longest = max((len(run) for run in re.findall(r"`+", folded)), default=0)
    fence = "`" * (longest + 1)
    padding = " " if longest else ""
    return f"{fence}{padding}{folded.replace('|', chr(92) + '|')}{padding}{fence}"


def _markdown(entries: list[dict[str, Any]], project_title: str) -> str:
    title = _md_text(project_title)
    lines = [f"# Data dictionary — {title}" if title else "# Data dictionary", ""]
    lines.append(
        "Every file of this export, and what each column of its tables means. Shares are fractions from 0 to 1; "
        "an empty cell is a value that does not exist for that row (not a zero). In a CSV, text that a spreadsheet "
        "would run as a formula (a channel title beginning with `=`, `+`, `-` or `@`) is written behind an "
        "apostrophe: strip it when reading that column with other software."
    )
    group = None
    for entry in entries:
        if entry["group"] != group:
            group = entry["group"]
            lines.extend(["", f"## {group}"])
        lines.extend(["", f"### {_md_code(entry['name'])}", "", _md_text(entry["description"])])
        for sheet in entry["sheets"]:
            if sheet["sheet"]:
                about = f": {_md_text(sheet['description'])}" if sheet["description"] else ""
                lines.extend(["", f"Sheet {_md_code(sheet['sheet'])}{about}"])
            lines.extend(["", "| Column | Meaning |", "|---|---|"])
            for header, meaning in sheet["columns"]:
                lines.append(f"| {_md_code(header)} | {_md_text(meaning)} |")
    return "\n".join(lines) + "\n"


def _summary(root: str) -> dict[str, Any]:
    try:
        with open(os.path.join(root, "summary.json"), encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def write(root: str, *, project_title: str = "", seo: bool = False) -> None:
    """Write ``DATA.md`` and ``data.html`` at the export root.

    The page carries the export's own date and Pulpit version (``summary.json``), so writing it again later
    (``compare_analysis``) does not re-date it.
    """
    from django.template.loader import render_to_string

    from network import publication, tables

    names = sorted(n for n in os.listdir(root) if os.path.isfile(os.path.join(root, n)) and n != DATA_MD)
    entries = dictionary(root, names)
    with open(os.path.join(root, DATA_MD), "w", encoding="utf-8") as f:
        f.write(_markdown(entries, project_title))
    summary = _summary(root)
    context = {
        **tables.page_context(
            DATA_PAGE,
            project_title,
            title="Data dictionary",
            description="Every file of this analysis and what each column of its tables means.",
            generated=str(summary.get("created_at") or "")[:10],
            app_version=str(summary.get("pulpit_version") or ""),
        ),
        "robots_meta": publication.robots_content(seo),
        "entries": entries,
    }
    context["page"]["question"] = "What does each file hold, and what does each column mean?"
    with open(os.path.join(root, DATA_PAGE), "w", encoding="utf-8") as f:
        f.write(render_to_string("network/data.html", context))
