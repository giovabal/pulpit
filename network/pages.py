"""The catalogue of the pages an export can hold: one entry per landing-page card.

Every reader-facing name of a page comes from here. That covers its title (the same on the landing
card, in the page heading and in the browser tab), the question it answers (the page's lede), its
landing-card summary, its short description for search engines, its group, its method document and
its downloads. ``network.site`` builds the landing page, the navigation and the page headers from it,
``network.publication`` the head tags, ``network.data_dictionary`` the file list of ``DATA.md``. The
module imports nothing from the rest of the package, so any of them can import it.
"""

from __future__ import annotations

import fnmatch
import re
from dataclasses import dataclass

LANDING_PAGE = "index.html"
# The timeline column of every per-period table (spreadsheets, CSVs) and its value for the full range.
PERIOD_HEADER = "Period"
ALL_PERIODS = "All periods"
# A compared analysis' copy of a page or download: ``channel_table.html`` → ``channel_table_2.html``.
COMPARED_SUFFIX = "_2"


@dataclass(frozen=True)
class Download:
    """A file of a card, by name or ``fnmatch`` pattern, with what it holds."""

    pattern: str
    label: str


@dataclass(frozen=True)
class Page:
    file: str
    title: str
    description: str = ""  # its own search-engine description, where a card's pages need different ones


@dataclass(frozen=True)
class Card:
    key: str
    group: str
    title: str
    icon: str
    question: str  # the page's lede: the question it answers
    summary: str  # the landing card's text
    description: str  # short description for search engines and link previews
    doc: str = ""  # method document, relative to the repository's docs/ ("network-measures.md#pagerank")
    pages: tuple[Page, ...] = ()
    downloads: tuple[Download, ...] = ()


# Landing-page sections, in reading order. The data files have a section of their own (network.site).
GROUPS: tuple[tuple[str, str], ...] = (
    ("maps", "Maps"),
    ("network", "Network structure"),
    ("channels", "Channels"),
    ("time", "Change over time"),
    ("content", "Content and audience"),
    ("resilience", "Resilience and succession"),
    ("comparison", "Comparison"),
)

CARDS: tuple[Card, ...] = (
    Card(
        key="structural_map",
        group="maps",
        title="Structural map",
        icon="map",
        question="How do the channels quote each other?",
        summary=(
            "Every dot is a channel; a line joins two channels when one forwards or mentions the other, and "
            "colours mark the groups they fall into. Zoom, search, and click a channel to inspect it."
        ),
        description=(
            "An interactive map of Telegram channels, showing how they connect through forwards and mentions."
        ),
        doc="graph-layouts.md",
        pages=(
            Page("graph.html", "Structural map"),
            Page(
                "graph3d.html",
                "Structural map (3D)",
                "A three-dimensional interactive map of Telegram channels, showing how they connect through "
                "forwards and mentions.",
            ),
        ),
    ),
    Card(
        key="coordination_map",
        group="maps",
        title="Coordination map",
        icon="stopwatch",
        question="Which channels repeatedly shared the same post within moments of one another?",
        summary=(
            "Links channels that forwarded the same posts within a short window, again and again: a possible "
            "sign they act together. It is about acting in sync, not about how often a channel is quoted."
        ),
        description=(
            "An interactive map of temporal co-forwarding coordination: Telegram channels linked when they "
            "repeatedly forwarded the same origin message within a short time window."
        ),
        doc="coordination-analysis.md",
        pages=(
            Page("coordination.html", "Coordination map"),
            Page(
                "coordination3d.html",
                "Coordination map (3D)",
                "A three-dimensional interactive map of temporal co-forwarding coordination: Telegram channels "
                "linked when they repeatedly forwarded the same origin message within a short time window.",
            ),
        ),
    ),
    Card(
        key="network",
        group="network",
        title="Network statistics",
        icon="bar-chart",
        question="How large, dense, reciprocal and clustered is the network, and how clearly does it split?",
        summary=(
            "The whole network in one table: its size, density, reciprocity and clustering, how far apart "
            "channels are, how sharply it divides into groups, and whether labels cite their own kind."
        ),
        description=(
            "The whole network of Telegram channels in one table: its size, density, reciprocity, clustering, "
            "distances and communities."
        ),
        doc="whole-network-statistics.md",
        pages=(Page("network_table.html", "Network statistics"),),
        downloads=(
            Download("network_table.xlsx", "Network statistics"),
            Download("network_label_flows.csv", "Label-to-label citation flows"),
        ),
    ),
    Card(
        key="communities",
        group="network",
        title="Community statistics",
        icon="diagram-3",
        question="Which groups of channels does each method find, and how do the methods agree?",
        summary=(
            "One table per grouping method: how big each community is, how tightly its members are linked and "
            "how much they cite outside it, with the agreement between the methods."
        ),
        description=(
            "The communities of Telegram channels: how big each is, how tightly its members are linked and how "
            "much they cite outside it."
        ),
        doc="community-detection.md",
        pages=(Page("community_table.html", "Community statistics"),),
        downloads=(Download("community_table.xlsx", "Community statistics"),),
    ),
    Card(
        key="consensus",
        group="network",
        title="Consensus matrix",
        icon="grid",
        question="Which channels land in the same community, whatever the method?",
        summary=(
            "Every pair of channels, by how often the grouping methods put them together: the larger and redder "
            "the circle, the more reliably the two belong together."
        ),
        description=(
            "How often each pair of Telegram channels lands in the same community across the community-detection "
            "methods."
        ),
        doc="community-detection.md#consensus-matrix",
        pages=(Page("consensus_matrix.html", "Consensus matrix"),),
    ),
    Card(
        key="channels",
        group="channels",
        title="Channels",
        icon="table",
        question="How active and how connected is each channel, and where does it sit in the network?",
        summary=(
            "One row per channel: its activity, how many channels it cites and is cited by, its influence "
            "scores such as PageRank, and the community each method puts it in."
        ),
        description=(
            "One row per Telegram channel: how active and connected it is, its influence scores and the "
            "communities it falls in."
        ),
        doc="network-measures.md",
        pages=(Page("channel_table.html", "Channels"),),
        downloads=(Download("channel_table.xlsx", "Channels"), Download("nodes.csv", "Channels")),
    ),
    Card(
        key="structural_equivalence",
        group="channels",
        title="Structural equivalence",
        icon="grid-3x3",
        question="Which channels hold interchangeable positions in the network?",
        summary=(
            "Every pair of channels, by who they cite and who cites them: two channels connected to the same "
            "others score high, whether or not they cite each other."
        ),
        description=(
            "Which Telegram channels hold interchangeable positions in the network: they cite, and are cited by, "
            "the same channels."
        ),
        doc="whole-network-statistics.md#structural-equivalence-matrix",
        pages=(Page("structural_equivalence.html", "Structural equivalence"),),
    ),
    Card(
        key="behavioural_equivalence",
        group="channels",
        title="Behavioural equivalence",
        icon="grid-3x3-gap",
        question="Which channels behave alike, wherever they sit in the network?",
        summary=(
            "Every pair of channels, by how they behave: how much they amplify others, how original and how fast "
            "they are, their following and how much they post."
        ),
        description=(
            "Which Telegram channels behave alike: how much they amplify others, how original and fast they are, "
            "and how much they post."
        ),
        doc="whole-network-statistics.md#behavioural-equivalence-matrix",
        pages=(Page("behavioural_equivalence.html", "Behavioural equivalence"),),
    ),
    Card(
        key="dominance",
        group="channels",
        title="Dominance",
        icon="arrow-left-right",
        question="When a forward is an endorsement, which channels depend on which?",
        summary=(
            "For every pair of channels with a citation between them: how much of each one's citing goes to the other, "
            "which direction holds up statistically, and a ranking of the channels."
        ),
        description=(
            "Which Telegram channels depend on which when a forward is an endorsement: pairwise dependence and a "
            "dominance ranking."
        ),
        doc="dominance.md",
        pages=(Page("dominance.html", "Dominance"),),
        downloads=(
            Download("dominance.xlsx", "Dominance"),
            Download("dominance_channels.csv", "Dominance ranking of the channels"),
            Download("dominance_pairs.csv", "Dependence of each pair"),
        ),
    ),
    Card(
        key="event_impact",
        group="time",
        title="Event impact",
        icon="calendar-event",
        question="Did the network change when a recorded event happened?",
        summary=(
            "For each recorded event: whether the network's weekly activity changed at that date, in level or "
            "in trend, beyond what the weeks before predict, tested against the same change at other dates."
        ),
        description=(
            "Whether the activity of the network of Telegram channels changed around recorded events, tested as "
            "interrupted time series."
        ),
        doc="event-impact.md",
        pages=(Page("event_impact.html", "Event impact"),),
        downloads=(
            Download("event_impact.xlsx", "Event impact"),
            Download("event_impact.csv", "Effects of each event"),
        ),
    ),
    Card(
        key="links",
        group="content",
        title="Outbound links",
        icon="box-arrow-up-right",
        question="Where do the channels send their readers?",
        summary=(
            "The web sites the channels link to, by category (donations, shops, mainstream and alternative "
            "platforms), who links where, and which channels share their sites beyond chance."
        ),
        description=(
            "The web sites Telegram channels send their readers to, by category, and which channels link to the "
            "same sites."
        ),
        doc="outbound-links.md",
        pages=(Page("links.html", "Outbound links"),),
        downloads=(
            Download("links.xlsx", "Outbound links"),
            Download("links_channel_sites.csv", "Links of each channel to each site"),
            Download("links_colinking.csv", "Co-linking pairs of channels"),
        ),
    ),
    Card(
        key="audience",
        group="content",
        title="Audience",
        icon="chat-dots",
        question="Who comments on the channels, and where else do they comment?",
        summary=(
            "The commenters of the channels: how concentrated the commenting is, how far commenters spread "
            "across channels and labels, which channels share them beyond chance, and whether they return."
        ),
        description=(
            "The commenters of Telegram channels: how concentrated the commenting is, how far commenters spread, "
            "and whether they return."
        ),
        doc="audience.md",
        pages=(Page("audience.html", "Audience"),),
        downloads=(Download("audience.xlsx", "Audience"), Download("audience_*.csv", "Audience")),
    ),
    Card(
        key="interesting_messages",
        group="content",
        title="Interesting messages",
        icon="stars",
        question="Which posts travelled furthest through the network?",
        summary=(
            "Posts ranked by how far they travelled: how many communities they reached, how influential the "
            "channels that picked them up are, and how much engagement they drew for their channel."
        ),
        description=(
            "Telegram posts ranked by how far they travelled: the communities they reached and the channels "
            "that picked them up."
        ),
        doc="interesting-messages.md",
        pages=(Page("interesting_messages.html", "Interesting messages"),),
    ),
    Card(
        key="robustness",
        group="resilience",
        title="Robustness",
        icon="shield-exclamation",
        question="Would the network fall apart if its most important channels were removed?",
        summary=(
            "How the network holds together as channels are removed one by one, in the order each attack "
            "strategy chooses, against random networks of the same make-up."
        ),
        description=(
            "How well the network of Telegram channels holds together as channels are removed, against random networks."
        ),
        doc="robustness-analysis.md",
        pages=(Page("robustness_table.html", "Robustness"),),
        downloads=(Download("robustness_table.xlsx", "Robustness"),),
    ),
    Card(
        key="vacancy",
        group="resilience",
        title="Vacancy analysis",
        icon="person-dash",
        question="When a channel closed, which channels took its place?",
        summary=(
            "For each channel that closed, a ranked shortlist of the channels most likely to have taken its "
            "place, by how much they share its audience, its connections and its content."
        ),
        description=(
            "For each Telegram channel that closed, the channels most likely to have taken its place, by shared "
            "audience, connections and content."
        ),
        doc="vacancy-analysis.md",
        pages=(Page("vacancy_analysis.html", "Vacancy analysis"),),
    ),
    Card(
        key="compare",
        group="comparison",
        title="Network comparison",
        icon="intersect",
        question="How do two analyses of the network differ?",
        summary="The whole-network statistics of the two analyses side by side, with their distributions overlaid.",
        description="Side-by-side statistics and scatter plots of two analyses of a network of Telegram channels.",
        doc="export-formats.md#network_compare_tablehtml--network-comparison",
        pages=(Page("network_compare_table.html", "Network comparison"),),
    ),
)

_PAGE_INDEX: dict[str, tuple[Card, Page]] = {page.file: (card, page) for card in CARDS for page in card.pages}


def compared_name(name: str) -> str:
    """The compared analysis' copy of the file *name* (``a.html`` → ``a_2.html``)."""
    stem, dot, ext = name.rpartition(".")
    return f"{stem}{COMPARED_SUFFIX}.{ext}" if dot else name + COMPARED_SUFFIX


def original_name(name: str) -> str | None:
    """The file a compared copy stands for (``a_2.html`` → ``a.html``), ``None`` for any other file."""
    stem, dot, ext = name.rpartition(".")
    if dot and stem.endswith(COMPARED_SUFFIX):
        return f"{stem[: -len(COMPARED_SUFFIX)]}.{ext}"
    return None


def lookup(page: str) -> tuple[Card, Page, bool] | None:
    """The card and catalogue page of the export page *page*, and whether it is a compared copy."""
    if page in _PAGE_INDEX:
        return (*_PAGE_INDEX[page], False)
    original = original_name(page)
    if original in _PAGE_INDEX:
        return (*_PAGE_INDEX[original], True)
    return None


def page_title(page: str) -> str:
    """The reader-facing title of *page*, ``""`` for a page the catalogue does not know."""
    found = lookup(page)
    if found is None:
        return ""
    _card, entry, compared = found
    return f"{entry.title} (compared analysis)" if compared else entry.title


def page_description(page: str) -> str:
    """The short description of *page* for search engines, ``""`` for a page the catalogue does not know."""
    found = lookup(page)
    if found is None:
        return ""
    found_card, entry, compared = found
    description = entry.description or found_card.description
    if compared:
        return f"{description.rstrip('.')}, in the compared analysis."
    return description


def downloads_of(found_card: Card, names: list[str], *, compared: bool = False) -> list[tuple[str, str]]:
    """``(file, label)`` of the card's downloads present among *names*, in catalogue order."""
    out: list[tuple[str, str]] = []
    seen: set[str] = set()
    for download in found_card.downloads:
        pattern = compared_name(download.pattern) if compared else download.pattern
        for name in sorted(fnmatch.filter(names, pattern)):
            if name not in seen:
                seen.add(name)
                out.append((name, _download_label(download, name)))
    return out


def _download_label(download: Download, name: str) -> str:
    """The label of one file of a download: a pattern's files are told apart by the part the ``*`` matched
    (``audience_*.csv`` + ``audience_overlap.csv`` → ``Audience: overlap``)."""
    if "*" not in download.pattern:
        return download.label
    head, _, tail = download.pattern.partition("*")
    part = name[len(head) : len(name) - len(tail)] if name.startswith(head) and name.endswith(tail) else ""
    return f"{download.label}: {part.replace('_', ' ')}" if part else download.label


_RELEASE_RE = re.compile(r"^\d+(\.\d+)*$")


def docs_ref(app_version: str) -> str:
    """The git ref the method links of an export point at: the release tag of its version, else ``main``.

    A development build (``0.30dev``) has no tag yet, and its methods are those of ``main``.
    """
    return f"v{app_version}" if _RELEASE_RE.match(app_version or "") else "main"


def docs_url(repository_url: str, app_version: str, doc: str) -> str:
    """Address of the method document *doc* as it stood in the version that produced the export."""
    if not repository_url or not doc:
        return ""
    return f"{repository_url.rstrip('/')}/blob/{docs_ref(app_version)}/docs/{doc}"
