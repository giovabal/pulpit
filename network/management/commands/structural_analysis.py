import argparse
import datetime
import os
import re
import shutil
import tempfile
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db.models import Max, Min
from django.utils import timezone

from network import (
    community,
    community_stats,
    coordination,
    exporter,
    graph_builder,
    interest_structural,
    layout,
    measures,
    robustness,
    tables,
    vacancy_analysis,
)
from network.graph_builder import VALID_EDGE_WEIGHT_STRATEGIES
from network.robustness.disparity_filter import disparity_filter
from network.tokens import split_tokens
from network.utils import GraphData
from webapp import scoring
from webapp.models import Message, Project
from webapp.utils.channel_types import VALID_CHANNEL_TYPES
from webapp.utils.colors import is_known_palette
from webapp_engine.command_logging import styled_warning_logs

import networkx as nx


def _parse_csv(value: str) -> list[str]:
    """Split a comma-separated string into a list of uppercase tokens.

    Parenthesis-aware: the comma inside a multi-parameter token like
    ``LEIDEN_TEMPORAL(resolution=0.05,interslice=1.0)`` does not split it.
    """
    return [s.upper() for s in split_tokens(value)]


# ── Extra-layout dispatch ────────────────────────────────────────────────────
# Centralised so adding a new layout means editing one map plus
# `network.layout.EXTRA_LAYOUT_CHOICES_2D` / `_3D`, instead of three places.

_EXTRA_LAYOUT_FUNCS_2D: dict[str, Any] = {
    "CIRCULAR": layout.circular_positions,
    "KAMADA_KAWAI": layout.kamada_kawai_positions,
    "TSNE": layout.tsne_positions_2d,
    "UMAP": layout.umap_positions_2d,
    "HYPERBOLIC": layout.hyperbolic_positions,
    # COMMUNITY_SHELL needs the strategy_results, so it's resolved lazily below.
}

_EXTRA_LAYOUT_FUNCS_3D: dict[str, Any] = {
    "SPECTRAL": layout.spectral_positions,
    "SPRING": layout.spring_positions,
    "KAMADA_KAWAI": layout.kamada_kawai_positions_3d,
    "TSNE": layout.tsne_positions_3d,
    "UMAP": layout.umap_positions_3d,
}


def _compute_extra_layouts(
    graph: nx.DiGraph,
    names: list[str],
    *,
    dim: int = 2,
    strategy_results: dict | None = None,
    on_progress: Callable[[str], None] | None = None,
) -> dict[str, dict]:
    """Compute every extra layout in ``names`` (excluding FA2, which is the
    primary layout) and return ``{lower_case_name: positions}``."""
    funcs = _EXTRA_LAYOUT_FUNCS_2D if dim == 2 else _EXTRA_LAYOUT_FUNCS_3D
    out: dict[str, dict] = {}
    for name in names:
        if name == "FA2":
            continue
        if on_progress is not None:
            on_progress(name)
        if dim == 2 and name == "COMMUNITY_SHELL":
            out[name.lower()] = layout.community_shell_positions(graph, strategy_results or {})
        else:
            out[name.lower()] = funcs[name](graph)
    return out


def _pick_interest_community_strategy(strategies: "list[community.StrategyInstance]") -> str:
    """Pick the community-partition *key* used by interest-structural's C metric.

    Prefer LEIDEN_DIRECTED (directional brokerage makes more sense for forwarding cascades than
    undirected modularity), then LEIDEN, then any non-metadata (algorithmic) strategy, then a manual
    ``LABELGROUP<id>`` partition as a last resort. Returns the chosen instance's node-attribute key
    (e.g. ``leiden_directed`` or ``leiden_cpm_resolution_0_05``); the first instance of a family wins.
    """
    by_name: dict[str, community.StrategyInstance] = {}
    for inst in strategies:
        by_name.setdefault(inst.name, inst)
    for candidate in ("LEIDEN_DIRECTED", "LEIDEN", "LEIDEN_CPM"):
        if candidate in by_name:
            return by_name[candidate].key
    for inst in strategies:
        if not community.is_metadata_strategy(inst.name):
            return inst.key
    if strategies:
        return strategies[0].key  # only manual LABELGROUP partitions available
    raise CommandError("--interest-structural requires at least one community strategy in --community-strategies.")


def _pick_interest_authority_key(present_measures: "set[str]") -> str:
    """Choose the node attribute used as D's authority weight.

    ``present_measures`` is the set of requested measure *names* (instance parameters are
    irrelevant here — PAGERANK and HITSAUTH take none). Falls through PAGERANK → HITSAUTH →
    in_deg (always populated by ``apply_base_node_measures``)."""
    if "PAGERANK" in present_measures:
        return "pagerank"
    if "HITSAUTH" in present_measures:
        return "hits_authority"
    return "in_deg"


# Progress-line phrase per measure token (the "- … done" lines during computation).
_MEASURE_PROGRESS: dict[str, str] = {
    "PAGERANK": "pagerank",
    "INDEGCENTRALITY": "in-degree centrality",
    "OUTDEGCENTRALITY": "out-degree centrality",
    "BURTCONSTRAINT": "Burt's constraint",
    "LOCALCLUSTERING": "local clustering",
    "RECIPROCITY": "reciprocity",
    "AMPLIFICATION": "amplification factor",
    "CONTENTORIGINALITY": "content originality",
    "DIFFUSIONLAG": "diffusion lag",
    "HITSHUB": "HITS hub",
    "HITSAUTH": "HITS authority",
    "MODULEROLE": "module role",
}


def _rebind_measure_keys(
    graph_data: GraphData,
    instance: "measures.MeasureInstance",
    returned_labels: list[tuple[str, str]],
) -> list[tuple[str, str]]:
    """Move a parameterised instance's bare node keys to their parameter-suffixed form.

    The ``apply_*`` functions always write their canonical bare keys (e.g.
    ``within_module_z``, plus categorical companions like ``module_role``). For a
    parameterised instance every numeric (returned) key *and* every categorical aux key
    declared on the measure spec is renamed to ``<base><suffix>`` on every node, so two
    instances of the same measure never overwrite each other's columns. Returns the
    suffixed ``(key, label)`` pairs (label annotated with the parameters) for
    ``measures_labels``; a no-param instance is returned unchanged.
    """
    suffix = instance.suffix()
    if not suffix:
        return list(returned_labels)
    spec = instance.spec
    rename = {k: k + suffix for k, _ in returned_labels}
    if spec:
        rename.update({k: k + suffix for k in spec.aux_keys})
    for node in graph_data["nodes"]:
        for old, new in rename.items():
            if old in node:
                node[new] = node.pop(old)
    annotation = instance.label_annotation()
    return [(k + suffix, f"{lbl}{annotation}") for k, lbl in returned_labels]


def _resolve_community_basis(
    instance: "measures.MeasureInstance",
    available_bases: "list[str]",
) -> str | None:
    """Resolve the concrete community-partition key for a partition-based measure instance.

    ``available_bases`` is the ordered list of partition keys present on the graph (selection order).
    An explicit ``basis`` is matched first as an exact instance key, then as a strategy *family* —
    resolving to the first selected instance of that family (e.g. ``basis=LEIDEN_CPM`` →
    ``leiden_cpm_resolution_0_01`` when that is the first CPM instance). An empty/auto basis falls
    through to LEIDEN_DIRECTED, then any available partition. Returns None when none is available.
    """

    def _family_match(family: str) -> str | None:
        if family in available_bases:
            return family
        return next((b for b in available_bases if community.canonical_strategy_key(b) == family), None)

    explicit = (instance.params_dict.get("basis") or "").lower()
    if explicit:
        return _family_match(explicit)
    match = _family_match("leiden_directed")
    if match:
        return match
    return available_bases[0] if available_bases else None


def _date_window_filter(start_date: datetime.date | None, end_date: datetime.date | None) -> dict[str, Any]:
    """Build ORM filter kwargs for ``Message.date`` from the export window.

    Returns ``{}`` when both bounds are absent — callers treat that as the
    "use Message.interest_score field, span all-time forwards" sentinel.
    """
    out: dict[str, Any] = {}
    if start_date is not None:
        out["date__date__gte"] = start_date
    if end_date is not None:
        out["date__date__lte"] = end_date
    return out


def _timeline_year_range(start_date: datetime.date | None, end_date: datetime.date | None) -> "tuple[int, int] | None":
    """First/last calendar year of the timeline export, or ``None`` when no messages exist.

    localdate(): the per-year exports filter messages by TIME_ZONE calendar days
    (``date__date__gte/lte``), so the bounds must use the same convention — a newest message in
    the next *local* year past the UTC max would otherwise appear in no year export at all.
    Shared by the timeline loop and the LEIDEN_TEMPORAL precompute so both walk identical years.
    """
    year_agg = Message.objects.aggregate(min_date=Min("date"), max_date=Max("date"))
    min_date, max_date = year_agg["min_date"], year_agg["max_date"]
    if min_date is None:
        return None
    min_local, max_local = timezone.localdate(min_date), timezone.localdate(max_date)
    first_year = max(min_local.year, start_date.year) if start_date else min_local.year
    last_year = min(max_local.year, end_date.year) if end_date else max_local.year
    return first_year, last_year


def _clamp_year_window(
    year: int, window_start: datetime.date | None, window_end: datetime.date | None
) -> tuple[datetime.date, datetime.date]:
    """Clamp a calendar year to the user's --startdate/--enddate window (shared with the year loop)."""
    start_date = datetime.date(year, 1, 1)
    end_date = datetime.date(year, 12, 31)
    if window_start and window_start > start_date:
        start_date = window_start
    if window_end and window_end < end_date:
        end_date = window_end
    return start_date, end_date


def _atomic_publish(staging: str, final_target: str) -> None:
    """Atomically swap ``staging`` into ``final_target``.

    Two-step rename: ``final_target`` → ``final_target.old`` → cleanup of staging.
    ``os.rename`` is atomic per inode on POSIX but cannot replace a non-empty
    directory, hence the intermediate ``.old`` directory.
    """
    old = final_target + ".old"
    if os.path.isdir(final_target):
        os.rename(final_target, old)
    os.rename(staging, final_target)
    if os.path.isdir(old):
        shutil.rmtree(old, ignore_errors=True)


@dataclass(frozen=True)
class ResolvedOptions:
    """All options the command needs, resolved from CLI flags.

    Built once at the top of ``handle`` so downstream helpers can take a single
    object rather than 30 individual kwargs. Missing flags resolve to typed
    no-op literals; the few config-derived fallbacks (channel types, edge-weight
    strategy, community palette, dead-leaves colour) are noted in
    ``_resolve_options``.
    """

    # Output toggles
    do_graph: bool
    do_3dgraph: bool
    do_html: bool
    do_xlsx: bool
    do_gexf: bool
    do_graphml: bool
    do_csv: bool
    do_consensus_matrix: bool
    do_structural_similarity: bool
    do_behavioural_equivalence: bool

    # Layout / presentation
    seo: bool
    vertical_layout: bool
    target_layout: str
    # Raw value: either an int (e.g. 5000) or a string with optional "x" suffix
    # (e.g. "7x" = 7 × channel count). Resolved against the graph node count
    # inside _compute_layout via layout.resolve_iterations().
    fa2_iterations: str | int
    extra_layout_names: list[str]
    extra_layout_names_3d: list[str]

    # Graph build / scope
    start_date: datetime.date | None
    end_date: datetime.date | None
    draw_dead_leaves: bool
    dead_leaves_color: str | None
    community_palette: str
    community_palette_reversed: bool
    include_mentions: bool
    include_self_references: bool
    include_lost: bool
    include_private: bool
    channel_types: list[str]
    channel_sources: list[str]
    edge_weight_strategy: str

    # Communities and measures
    communities_strategy: list["community.StrategyInstance"]
    strategies_lower: list[str]  # parameter-suffixed partition keys, one per instance, in order
    # Disparity-filter α applied to the graph before the algorithmic community detections
    # (0 = off, detection runs on the full graph). Label-group partitions are unaffected.
    community_backbone_alpha: float
    # Ordered, de-duplicated list of requested measures, each carrying its own resolved
    # parameters (a measure may appear more than once with different params — e.g. two
    # DIFFUSIONLAG windows).
    measure_instances: list[measures.MeasureInstance]
    selected_network_groups: frozenset[str]

    # Tunable measure / strategy parameters
    diffusion_window: int
    leiden_cpm_resolution: float
    community_distribution_threshold: int

    # Timeline
    timeline_step: str

    # Vacancy analysis
    selected_vacancy_measures: set[str] = field(default_factory=set)
    vacancy_months_before: int = 0
    vacancy_months_after: int = 0
    vacancy_max_candidates: int = 0

    # Robustness analysis
    do_robustness: bool = False
    robustness_alpha: float = 0.05
    robustness_strategies: list[str] = field(default_factory=list)
    robustness_runs: int = 100
    robustness_null: int = 20
    robustness_seed: int = 42
    robustness_sample: int = 500

    # Interest structural analysis (per-message C + D)
    do_interest_structural: bool = False
    interest_window_days: int = 30
    interest_include_mentions: bool = False

    # Coordination analysis (temporal co-forwarding)
    do_coordination_2d: bool = False
    do_coordination_3d: bool = False
    coordination_window: int = 300
    coordination_min_events: int = 3

    # Export naming
    export_name: str = ""

    @property
    def do_vacancy(self) -> bool:
        return bool(self.selected_vacancy_measures)

    @property
    def do_coordination(self) -> bool:
        return self.do_coordination_2d or self.do_coordination_3d

    def to_options_dict(self) -> dict[str, Any]:
        """Compatibility shim: ``_run_year_export`` still takes a plain dict."""
        return {
            "graph": self.do_graph,
            "graph_3d": self.do_3dgraph,
            "html": self.do_html,
            "xlsx": self.do_xlsx,
            "gexf": self.do_gexf,
            "graphml": self.do_graphml,
            "csv": self.do_csv,
            "consensus_matrix": self.do_consensus_matrix,
            "structural_similarity": self.do_structural_similarity,
            "behavioural_equivalence": self.do_behavioural_equivalence,
            "seo": self.seo,
            "vertical_layout": self.vertical_layout,
            "fa2_iterations": self.fa2_iterations,
            "draw_dead_leaves": self.draw_dead_leaves,
            "dead_leaves_color": self.dead_leaves_color,
            "community_palette": self.community_palette,
            "community_palette_reversed": self.community_palette_reversed,
            "include_mentions": self.include_mentions,
            "include_self_references": self.include_self_references,
            "include_lost": self.include_lost,
            "include_private": self.include_private,
            "timeline_step": self.timeline_step,
            "diffusion_window": self.diffusion_window,
            "leiden_cpm_resolution": self.leiden_cpm_resolution,
            "community_backbone_alpha": self.community_backbone_alpha,
            "community_distribution_threshold": self.community_distribution_threshold,
            "vacancy_months_before": self.vacancy_months_before,
            "vacancy_months_after": self.vacancy_months_after,
            "vacancy_max_candidates": self.vacancy_max_candidates,
            "robustness": self.do_robustness,
            "robustness_alpha": self.robustness_alpha,
            "robustness_strategies": ",".join(self.robustness_strategies) if self.robustness_strategies else "",
            "robustness_runs": self.robustness_runs,
            "robustness_null": self.robustness_null,
            "robustness_seed": self.robustness_seed,
            "robustness_sample": self.robustness_sample,
            "interest_structural": self.do_interest_structural,
            "interest_window_days": self.interest_window_days,
            "interest_include_mentions": self.interest_include_mentions,
            "coordination_2d": self.do_coordination_2d,
            "coordination_3d": self.do_coordination_3d,
            "coordination_window": self.coordination_window,
            "coordination_min_events": self.coordination_min_events,
        }


class Command(BaseCommand):
    args = ""
    help = "Build the network graph, compute measures, detect communities, and export output files."

    def add_arguments(self, parser: Any) -> None:
        # Every output toggle uses BooleanOptionalAction (default=None) so the
        # Operations panel's unchecked boxes can emit --no-X and beat a saved-true
        # default. Same shape as the crawl_channels toggles (commit 5737cac).
        parser.add_argument(
            "--graph-2d",
            "--2dgraph",  # backward-compat alias for the original cryptic name
            dest="graph",
            action=argparse.BooleanOptionalAction,
            default=None,
            help="Generate the structural 2D map (graph.html) — the interactive citation graph — including layout computation.",
        )
        parser.add_argument(
            "--graph-3d",
            "--3dgraph",  # backward-compat alias
            dest="graph_3d",
            action=argparse.BooleanOptionalAction,
            default=None,
            help="Also produce the structural 3D map (graph3d.html). Slower on large graphs.",
        )
        parser.add_argument(
            "--html",
            dest="html",
            action=argparse.BooleanOptionalAction,
            default=None,
            help="Generate HTML table output (channel_table.html, network_table.html, community_table.html).",
        )
        parser.add_argument(
            "--xlsx",
            dest="xlsx",
            action=argparse.BooleanOptionalAction,
            default=None,
            help="Also produce Excel spreadsheet output (channel_table.xlsx, network_table.xlsx, community_table.xlsx).",
        )
        parser.add_argument(
            "--gexf",
            dest="gexf",
            action=argparse.BooleanOptionalAction,
            default=None,
            help="Also write network.gexf with all computed measures embedded as node attributes.",
        )
        parser.add_argument(
            "--graphml",
            dest="graphml",
            action=argparse.BooleanOptionalAction,
            default=None,
            help="Also write network.graphml with all computed measures embedded as node attributes.",
        )
        parser.add_argument(
            "--csv",
            dest="csv",
            action=argparse.BooleanOptionalAction,
            default=None,
            help="Also write nodes.csv (one row per channel, same columns as channel_table.xlsx) and edges.csv (source_label, target_label, weight, weight_forwards, weight_mentions).",
        )
        parser.add_argument(
            "--seo",
            action=argparse.BooleanOptionalAction,
            default=None,
            help=(
                "Optimise the output mini-site for search engine discovery: sets indexable robots tags "
                "and adds meta descriptions. Without this flag the output actively discourages indexing."
            ),
        )
        parser.add_argument(
            "--startdate",
            default=None,
            metavar="YYYY-MM-DD",
            help="Only include messages on or after this date.",
        )
        parser.add_argument(
            "--enddate",
            default=None,
            metavar="YYYY-MM-DD",
            help="Only include messages on or before this date.",
        )
        parser.add_argument(
            "--fa2-iterations",
            dest="fa2_iterations",
            type=str,
            default=None,
            metavar="N|Nx",
            help=(
                "Number of ForceAtlas2 iterations for the 2D and 3D layout. "
                "Either an integer (e.g. 5000) or a multiplier of the number of "
                "channels in the graph (e.g. 7x → 7 × channel count). "
                "Floored at 100 iterations regardless. Default: 7x."
            ),
        )
        parser.add_argument(
            "--vertical-layout",
            dest="vertical_layout",
            action=argparse.BooleanOptionalAction,
            default=None,
            help=(
                "Orient the graph vertically. By default the layout is horizontal. "
                "When the computed aspect ratio does not match the chosen orientation the graph is rotated 90°."
            ),
        )
        parser.add_argument(
            "--layouts-2d",
            "--2dlayouts",  # backward-compat alias
            dest="layouts_2d",
            default=None,
            metavar="LAYOUTS",
            help=(
                "Comma-separated list of 2D layout algorithms to compute. "
                "When omitted, ForceAtlas2 (FA2) is computed as the only layout. "
                "The browser graph viewer offers a dropdown to switch between them at viewing time. "
                "Available: FA2, CIRCULAR, KAMADA_KAWAI, COMMUNITY_SHELL, TSNE, UMAP, HYPERBOLIC, ALL. Requires --graph-2d."
            ),
        )
        parser.add_argument(
            "--layouts-3d",
            "--3dlayouts",  # backward-compat alias
            dest="layouts_3d",
            default=None,
            metavar="LAYOUTS",
            help=(
                "Comma-separated list of 3D layout algorithms to compute. "
                "When omitted, ForceAtlas2 (FA2) is computed as the only layout. "
                "The structural 3D map's viewer offers a dropdown to switch between them at viewing time. "
                "Available: FA2, SPECTRAL, SPRING, KAMADA_KAWAI, TSNE, UMAP, ALL. Requires --graph-3d."
            ),
        )
        parser.add_argument(
            "--measures",
            dest="measures",
            default=None,
            metavar="MEASURES",
            help=(
                "Comma-separated list of centrality measures to compute. "
                "Available: PAGERANK, HITSHUB, HITSAUTH, INDEGCENTRALITY, OUTDEGCENTRALITY, "
                "BURTCONSTRAINT, LOCALCLUSTERING, RECIPROCITY, "
                "MODULEROLE (Guimerà-Amaral role; needs a community strategy; emits within-module z "
                "and the participation coefficient plus the categorical role label), "
                "AMPLIFICATION, CONTENTORIGINALITY, DIFFUSIONLAG, ALL. "
                "Default: no measures. "
                "Parameterised measures take keyword arguments in parentheses and may be listed more "
                "than once with different parameters: DIFFUSIONLAG(window=60), MODULEROLE(basis=LEIDEN). "
                "A bare DIFFUSIONLAG inherits --diffusion-window as its default; each parameter "
                "combination produces its own parameter-suffixed output column."
            ),
        )
        parser.add_argument(
            "--community-strategies",
            dest="community_strategies",
            default=None,
            metavar="STRATEGIES",
            help=(
                "Comma-separated list of community detection algorithms to apply. "
                "Available: LEIDEN, LEIDEN_DIRECTED, LEIDEN_CPM, LEIDEN_TEMPORAL, LOUVAIN, KCORE, SBM, "
                "SBM_ASSORTATIVE, CONSENSUS, "
                "LABELGROUP<id> (the manual partition induced by partition LabelGroup <id>), ALL. "
                "LEIDEN_CPM takes a keyword resolution and may repeat: LEIDEN_CPM(resolution=0.05). "
                "LEIDEN_TEMPORAL(resolution=…, interslice=…) couples the per-year timeline slices into one "
                "temporal partition with stable community ids across years (Mucha et al. 2010); requires "
                "--timeline-step year and is NOT included in ALL. "
                "SBM (directed degree-corrected stochastic block model) takes mode=FLAT|NESTED, "
                "weights=POISSON|EXPONENTIAL, refine=MCMC; SBM_ASSORTATIVE (Bayesian planted partition, "
                "statistically supported cohesive communities) takes refine=MCMC; both require graph-tool "
                "(conda/apt, not pip). "
                "CONSENSUS(threshold=0.5) is the Lancichinetti-Fortunato consensus of the other selected "
                "algorithmic strategies (KCORE and LEIDEN_TEMPORAL excluded) and needs at least two of them. "
                "LOUVAIN is the classic modularity baseline kept for comparison with older studies; "
                "prefer LEIDEN / LEIDEN_DIRECTED otherwise. "
                "Default: no community detection."
            ),
        )
        parser.add_argument(
            "--network-stat-groups",
            dest="network_stat_groups",
            default=None,
            metavar="GROUPS",
            help=(
                "Comma-separated list of whole-network stat groups to compute (requires --html, --xlsx, or "
                "--consensus-matrix). Available: SIZE, PATHS, COHESION, COMPONENTS, DEGCORRELATION, "
                "CENTRALIZATION, CONTENT, ALL. "
                "Default: none — pass ALL explicitly."
            ),
        )
        parser.add_argument(
            "--mentions",
            dest="include_mentions",
            action=argparse.BooleanOptionalAction,
            default=None,
            help=(
                "Include t.me/ mention references as edges alongside forwards "
                "(default: off). Use --no-mentions to force forwards only."
            ),
        )
        parser.add_argument(
            "--self-references",
            dest="include_self_references",
            action=argparse.BooleanOptionalAction,
            default=None,
            help=(
                "Include self-references (a channel forwarding from or mentioning itself) as "
                "self-loop edges in the graph (default: off). "
                "Only mention-based self-references are affected by --no-mentions."
            ),
        )
        parser.add_argument(
            "--edge-weight-strategy",
            dest="edge_weight_strategy",
            default=None,
            choices=sorted(VALID_EDGE_WEIGHT_STRATEGIES),
            metavar="STRATEGY",
            help=(
                "How edge weights are computed from forward and citation counts. "
                "NONE = all edges equal weight; TOTAL = raw count; "
                "PARTIAL_MESSAGES = count / total messages; "
                "PARTIAL_REFERENCES = count / forwarded-or-citing messages. "
                "Defaults to the [edges].weight_strategy entry in "
                "configuration/.operations-structural, else PARTIAL_REFERENCES."
            ),
        )
        parser.add_argument(
            "--diffusion-window",
            dest="diffusion_window",
            type=int,
            default=None,
            metavar="DAYS",
            help=(
                "Reaction window in days for the DIFFUSIONLAG measure: only forwards within this many days of the "
                "original post are included. Use 0 to disable the window. Default: 30."
            ),
        )
        parser.add_argument(
            "--draw-dead-leaves",
            dest="draw_dead_leaves",
            action=argparse.BooleanOptionalAction,
            default=None,
            help=(
                "Include dead leaves in the graph: out-of-target channels that an in-target channel has "
                "forwarded from or mentioned via a t.me/ link."
            ),
        )
        parser.add_argument(
            "--dead-leaves-color",
            dest="dead_leaves_color",
            type=str,
            default=None,
            metavar="#RRGGBB",
            help=(
                "Override the hex colour applied to dead-leaf nodes (out-of-target channels forwarded "
                "from or mentioned by in-target ones). Only effective when --draw-dead-leaves is set. "
                "Falls back to the dead_leaves_color entry in configuration/.operations-structural."
            ),
        )
        parser.add_argument(
            "--community-palette",
            dest="community_palette",
            type=str,
            default=None,
            metavar="NAME",
            help=(
                "pypalettes palette name used to colour communities for every algorithmic "
                "(non-LABELGROUP) strategy. Falls back to the community_palette entry in "
                "configuration/.operations-structural. Default: vaporwave."
            ),
        )
        parser.add_argument(
            "--community-palette-reversed",
            dest="community_palette_reversed",
            action=argparse.BooleanOptionalAction,
            default=None,
            help=(
                "Reverse the palette colour order so community #1 (the largest) receives the last "
                "colour. Default: on (matches the historical vaporwave-reversed look). Pair with "
                "--no-community-palette-reversed to apply the palette in its canonical order."
            ),
        )
        parser.add_argument(
            "--leiden-cpm-resolution",
            dest="leiden_cpm_resolution",
            type=float,
            default=None,
            metavar="γ",
            help=(
                "Default CPM resolution γ for a bare LEIDEN_CPM token. Communities form when their "
                "internal edge density exceeds γ. Reference points: γ ≈ 0.01 = fewer, larger communities; "
                "γ ≈ 0.05 = more, smaller communities. "
                "Default: 0.05. Override per instance with LEIDEN_CPM(resolution=…) and list it more than "
                "once for a multi-resolution scan."
            ),
        )
        # Deprecated: the two fixed CPM presets collapsed into one parameterised LEIDEN_CPM. These
        # aliases still seed the bare-token default (coarse preferred) for one release; prefer
        # --leiden-cpm-resolution or per-instance LEIDEN_CPM(resolution=…).
        parser.add_argument(
            "--leiden-coarse-resolution",
            dest="leiden_coarse_resolution",
            type=float,
            default=None,
            help=argparse.SUPPRESS,
        )
        parser.add_argument(
            "--leiden-fine-resolution", dest="leiden_fine_resolution", type=float, default=None, help=argparse.SUPPRESS
        )
        parser.add_argument(
            "--community-backbone-alpha",
            dest="community_backbone_alpha",
            type=float,
            default=None,
            metavar="α",
            help=(
                "Run the algorithmic community detections on the disparity-filter backbone "
                "(Serrano, Boguñá & Vespignani 2009) of the citation graph instead of the full graph: "
                "only edges carrying significantly more of a channel's citation weight than a uniform "
                "spread would predict (significance < α) are kept for detection. Values in (0, 1) filter "
                "(0.05 is the literature convention); 0 disables (default). Every other output — measures, "
                "layout, tables, exports — stays on the full graph; label-group partitions are unaffected. "
                "Reported modularity for the detected partitions is computed on the backbone they were "
                "optimised on."
            ),
        )
        parser.add_argument(
            "--consensus-matrix",
            dest="consensus_matrix",
            action=argparse.BooleanOptionalAction,
            default=None,
            help=(
                "Generate a consensus matrix page (consensus_matrix.html) showing how consistently "
                "each channel pair is co-clustered across all algorithmic (non-LABELGROUP) community "
                "detection strategies. Requires at least two algorithmic strategies."
            ),
        )
        parser.add_argument(
            "--structural-similarity",
            dest="structural_similarity",
            action=argparse.BooleanOptionalAction,
            default=None,
            help=(
                "Generate a structural equivalence matrix page (structural_similarity.html) showing "
                "pairwise cosine similarity of each channel's weighted in+out tie profile "
                "(Lorrain & White 1971): high = cite, and are cited by, the same channels."
            ),
        )
        parser.add_argument(
            "--behavioural-equivalence",
            dest="behavioural_equivalence",
            action=argparse.BooleanOptionalAction,
            default=None,
            help=(
                "Generate a behavioural equivalence matrix page (behavioural_equivalence.html) showing "
                "pairwise cosine similarity of channels' behavioural-measure profiles (amplification, "
                "content originality, diffusion lag, followers, message count); "
                "min-max normalised per measure, missing values imputed to the median."
            ),
        )
        parser.add_argument(
            "--community-distribution-threshold",
            dest="community_distribution_threshold",
            type=int,
            default=None,
            metavar="N",
            help=(
                "Minimum percentage (0–100) a community must reach in at least one organisation row "
                "to be shown in the Organisation × Community distribution cross-tab. "
                "Columns below this threshold in every row are hidden. "
                "Default: 0 (show all)."
            ),
        )
        parser.add_argument(
            "--channel-types",
            dest="channel_types",
            default=None,
            metavar="TYPES",
            help=(
                "Comma-separated list of Telegram entity types to include in the graph. "
                "Available: CHANNEL (broadcast channels), GROUP (supergroups/gigagroups), "
                "USER (user accounts and bots). Defaults to the DEFAULT_CHANNEL_TYPES setting "
                "([scope].channel_types in configuration/.operations-crawl)."
            ),
        )
        parser.add_argument(
            "--channel-sources",
            dest="channel_sources",
            default=None,
            metavar="SOURCES",
            help=(
                "Comma-separated list of ChannelSource keys. "
                "When provided, only channels belonging to at least one of these sources are included in the graph. "
                "Leave unset to include all in-target channels regardless of source membership."
            ),
        )
        parser.add_argument(
            "--include-lost",
            dest="include_lost",
            action=argparse.BooleanOptionalAction,
            default=None,
            help="Include channels marked as lost in the graph (excluded by default).",
        )
        parser.add_argument(
            "--include-private",
            dest="include_private",
            action=argparse.BooleanOptionalAction,
            default=None,
            help="Include channels marked as private in the graph (excluded by default).",
        )
        parser.add_argument(
            "--timeline-step",
            dest="timeline_step",
            default=None,
            choices=["none", "year"],
            help=(
                "Repeat the export for each calendar year found in the data. "
                "'none' disables this (default); 'year' generates per-year outputs "
                "(graph_YYYY.html, channel_table_YYYY.html, data_YYYY/, etc.) alongside "
                "the full-range export, and adds a Timeline section to the index."
            ),
        )
        # ── Vacancy analysis ──────────────────────────────────────────────────
        parser.add_argument(
            "--vacancy-measures",
            dest="vacancy_measures",
            default=None,
            metavar="MEASURES",
            help=(
                "Comma-separated list of vacancy succession algorithms to compute. "
                "Available: AMPLIFIER_JACCARD, STRUCTURAL_EQUIV, BROKERAGE, TEMPORAL, ALL. "
                "When at least one is selected, data/vacancy_analysis.json and "
                "vacancy_analysis.html are written for all vacancies in the database. "
                "Default: none (vacancy analysis disabled)."
            ),
        )
        parser.add_argument(
            "--vacancy-months-before",
            dest="vacancy_months_before",
            type=int,
            default=None,
            metavar="N",
            help="Look-back window (months) before each vacancy's death date. Default: 12.",
        )
        parser.add_argument(
            "--vacancy-months-after",
            dest="vacancy_months_after",
            type=int,
            default=None,
            metavar="N",
            help="Forward window (months) after each vacancy's death date. Default: 24.",
        )
        parser.add_argument(
            "--vacancy-max-candidates",
            dest="vacancy_max_candidates",
            type=int,
            default=None,
            metavar="N",
            help="Maximum replacement candidates scored per vacancy. Default: 30.",
        )
        # ── Robustness analysis ───────────────────────────────────────────────
        parser.add_argument(
            "--robustness",
            dest="robustness",
            action=argparse.BooleanOptionalAction,
            default=None,
            help=(
                "Enable the robustness analysis: residual-size R-index per attack strategy on "
                "the (optionally disparity-filtered) backbone, with z-score against a "
                "weight-rewiring null model and intra/inter community edge-survival curves. "
                "Writes data/robustness.json and (with --html) robustness_table.html. "
                "Passing --robustness-strategies implies this flag; "
                "use --no-robustness to disable explicitly (wins over the config file and the implication)."
            ),
        )
        parser.add_argument(
            "--robustness-alpha",
            dest="robustness_alpha",
            type=float,
            default=None,
            metavar="α",
            help=(
                "Disparity-filter threshold (Serrano et al. 2009) applied before the attacks. "
                "Values in (0, 1) keep statistically significant edges; 0 disables the filter "
                "and uses the full graph. Default: 0.05."
            ),
        )
        parser.add_argument(
            "--robustness-runs",
            dest="robustness_runs",
            type=int,
            default=None,
            metavar="N",
            help="Number of independent random-failure runs averaged for the 'random' strategy. Default: 100.",
        )
        parser.add_argument(
            "--robustness-null",
            dest="robustness_null",
            type=int,
            default=None,
            metavar="K",
            help=(
                "Number of weight-rewiring null-model simulations per strategy. "
                "0 disables the null model (no z-scores computed). Default: 20."
            ),
        )
        parser.add_argument(
            "--robustness-strategies",
            dest="robustness_strategies",
            default=None,
            metavar="STRATEGIES",
            help=(
                "Comma-separated list of attack strategies to run. Any of: "
                "random, in_strength, out_strength, pagerank, betweenness, subscribers, "
                "and the dynamic variants in_strength_dyn, out_strength_dyn, pagerank_dyn, "
                "betweenness_dyn. Use ALL for every strategy. "
                "Default: random,in_strength,out_strength,pagerank,betweenness. "
                "At least one strategy must be selected."
            ),
        )
        parser.add_argument(
            "--robustness-seed",
            dest="robustness_seed",
            type=int,
            default=None,
            metavar="N",
            help="Seed driving every stochastic component of the robustness analysis. Default: 42.",
        )
        parser.add_argument(
            "--robustness-sample",
            dest="robustness_sample",
            type=int,
            default=None,
            metavar="N",
            help=("Source-sample size for the R_reach metric on graphs larger than this many nodes. Default: 500."),
        )
        # ── Interest structural analysis (per-message C + D) ─────────────────
        parser.add_argument(
            "--interest-structural",
            dest="interest_structural",
            action=argparse.BooleanOptionalAction,
            default=None,
            help=(
                "Compute per-message cross-community reach (Goel et al. 2016 adapted to "
                "Telegram's depth-1 forwarding) and authority-weighted reach (Cha et al. 2010). "
                "Writes data/interest_structural.json. Requires at least one community "
                "strategy and ideally PAGERANK in --measures (falls back to HITSAUTH then "
                "in-degree)."
            ),
        )
        parser.add_argument(
            "--interest-window-days",
            dest="interest_window_days",
            type=int,
            default=None,
            metavar="DAYS",
            help=(
                "Reaction window in days for the structural interest scoring: only forwards "
                "within this many days of the origin post count toward C and D. Use 0 to "
                "disable the window. Default: 30 (matches --diffusion-window)."
            ),
        )
        parser.add_argument(
            "--interest-include-mentions",
            dest="interest_include_mentions",
            action=argparse.BooleanOptionalAction,
            default=None,
            help=(
                "Accept the flag for forward compatibility. Currently a no-op: Telegram's "
                "Message.references are message→channel, not message→message, so a faithful "
                "implementation needs separate design. A warning is logged when set."
            ),
        )
        # ── Coordination analysis (temporal co-forwarding) ────────────────────
        parser.add_argument(
            "--coordination-2d",
            dest="coordination_2d",
            action=argparse.BooleanOptionalAction,
            default=None,
            help=(
                "Build the temporal co-forwarding coordination layer and its 2D map "
                "(coordination.html): channels are tied when they repeatedly forward the same "
                "origin message within --coordination-window seconds, keeping pairs with at "
                "least --coordination-min-events shared origins. Writes data_coordination/ "
                "with its own force-directed layout. The coordination counterpart of --graph-2d."
            ),
        )
        parser.add_argument(
            "--coordination-3d",
            dest="coordination_3d",
            action=argparse.BooleanOptionalAction,
            default=None,
            help=(
                "Also (or only) produce the 3D coordination map (coordination3d.html) with its "
                "own 3D force-directed layout. The coordination counterpart of --graph-3d."
            ),
        )
        parser.add_argument(
            "--coordination-window",
            dest="coordination_window",
            type=int,
            default=None,
            metavar="SECONDS",
            help=(
                "Co-forwarding window in seconds: two forwards of the same origin message count as "
                "one coordinated event when they land within this many seconds of each other. "
                "Lower is stricter (automation-scale synchrony); higher also catches slower, "
                "human-paced pushes. Default: 300."
            ),
        )
        parser.add_argument(
            "--coordination-min-events",
            dest="coordination_min_events",
            type=int,
            default=None,
            metavar="N",
            help=(
                "Minimum number of distinct origin messages a channel pair must have co-forwarded "
                "inside the window before its coordination tie is kept. Repetition across different "
                "origins is what separates coordination from coincidence on viral content. Default: 3."
            ),
        )
        parser.add_argument(
            "--name",
            dest="name",
            default="",
            help=(
                "Name for this export. Output is written to exports/<name>/. "
                "If omitted, a YYYYMMDD-HHMMSS timestamp is used. "
                "Name is slug-sanitized (alphanumeric, hyphens, underscores)."
            ),
        )

    def _validate_settings(
        self,
        communities_strategy: list[str],
        measure_instances: "list[measures.MeasureInstance]",
        network_stat_groups: list[str],
        channel_types: list[str],
        edge_weight_strategy: str,
        vacancy_measures: list[str],
        do_interest_structural: bool = False,
    ) -> None:
        """Validate all settings. Raises CommandError on failure.

        Measure tokens and their parameters are already validated by ``measures.parse_measures``;
        here we only cross-check the *community-basis* parameters against --community-strategies
        (a basis that isn't computed cannot be read).
        """
        invalid_strategies = [
            i.name
            for i in communities_strategy
            if i.name not in community.VALID_STRATEGIES and not community.is_metadata_strategy(i.name)
        ]
        if invalid_strategies:
            valid = sorted(community.VALID_STRATEGIES) + community.labelgroup_strategy_tokens() + ["ALL"]
            raise CommandError(f"Invalid --community-strategies value(s): {invalid_strategies!r}. Choose from {valid}.")
        # Fail before the (hours-long) pipeline runs, not in the export phase where
        # _pick_interest_community_strategy would otherwise raise this after all the
        # layout/measure work has been discarded.
        if do_interest_structural and not communities_strategy:
            raise CommandError(
                "--interest-structural requires at least one community strategy in --community-strategies."
            )
        # CONSENSUS aggregates the other algorithmic partitions — fail up-front when fewer than two
        # eligible inputs are selected, mirroring detect_consensus (KCORE, LEIDEN_TEMPORAL, and the
        # manual label-group partitions don't count; neither does another CONSENSUS instance).
        if any(i.name == "CONSENSUS" for i in communities_strategy):
            eligible = [i for i in communities_strategy if community.consensus_eligible(i.name)]
            if len(eligible) < 2:
                raise CommandError(
                    "CONSENSUS needs at least two consensus-eligible input strategies in "
                    "--community-strategies (algorithmic strategies other than KCORE and "
                    f"LEIDEN_TEMPORAL; currently: {len(eligible)})."
                )
        # A measure basis names a strategy *family*; check it against the selected strategy names.
        strategy_names = {i.name for i in communities_strategy}
        for inst in measure_instances:
            if inst.measure == "MODULEROLE":
                basis = inst.params_dict.get("basis") or ""
                if basis and basis not in strategy_names:
                    raise CommandError(
                        f"{inst.token()} community basis {basis!r} is not in --community-strategies. "
                        f"Add it, or clear the basis to auto-resolve from the computed partitions."
                    )
        measure_names = {i.measure for i in measure_instances}
        if "MODULEROLE" in measure_names and not communities_strategy:
            raise CommandError(
                "MODULEROLE (Guimerà-Amaral role) needs a community partition: add at least one "
                "strategy to --community-strategies (LEIDEN_DIRECTED is the preferred basis)."
            )
        invalid_stat_groups = [g for g in network_stat_groups if g not in measures.VALID_NETWORK_STAT_GROUPS]
        if invalid_stat_groups:
            valid_display = sorted(measures.VALID_NETWORK_STAT_GROUPS) + ["ALL"]
            raise CommandError(
                f"Invalid --network-stat-groups value(s): {invalid_stat_groups!r}. Choose from {valid_display}."
            )
        invalid_channel_types = [t for t in channel_types if t not in VALID_CHANNEL_TYPES]
        if invalid_channel_types:
            raise CommandError(
                f"Invalid --channel-types value(s): {invalid_channel_types!r}. Choose from {sorted(VALID_CHANNEL_TYPES)}."
            )
        # Empty string is the no-op default — only validate non-empty values.
        if edge_weight_strategy and edge_weight_strategy not in VALID_EDGE_WEIGHT_STRATEGIES:
            raise CommandError(
                f"Invalid --edge-weight-strategy value: {edge_weight_strategy!r}. "
                f"Choose from {sorted(VALID_EDGE_WEIGHT_STRATEGIES)}."
            )
        invalid_vacancy = [m for m in vacancy_measures if m not in vacancy_analysis.VALID_VACANCY_MEASURES]
        if invalid_vacancy:
            valid_display = sorted(vacancy_analysis.VALID_VACANCY_MEASURES) + ["ALL"]
            raise CommandError(
                f"Invalid --vacancy-measures value(s): {invalid_vacancy!r}. Choose from {valid_display}."
            )

    def _parse_date(self, value: str | None, flag: str) -> datetime.date | None:
        if value is None:
            return None
        try:
            return datetime.date.fromisoformat(value)
        except ValueError as err:
            raise CommandError(f"Invalid date for {flag}: {value!r}. Expected format: yyyy-mm-dd.") from err

    def _compute_communities(
        self,
        graph: nx.DiGraph,
        channel_dict: dict,
        edge_list: list,
        communities_strategy: list[str],
        options: dict,
        temporal_results: "dict[str, tuple] | None" = None,
        year: "int | None" = None,
    ) -> tuple[dict[str, tuple], "nx.DiGraph | None"]:
        """Run all community detection strategies and apply results to the graph.

        Returns ``(strategy_results, detection_graph)``. ``detection_graph`` is the
        disparity-filter backbone the algorithmic detections ran on when
        ``--community-backbone-alpha`` is set (same vertex set as ``graph``, fewer edges), else
        ``None`` — the caller forwards it to ``compute_community_metrics`` so reported
        modularity matches what was optimised. Label-group partitions read the channels'
        labels, not the graph, so the backbone never affects them.

        ``temporal_results`` carries the LEIDEN_TEMPORAL precompute
        (``{instance.key: (per_year_maps, plurality_map, palette)}``, from
        ``_compute_temporal_partitions``); temporal instances are applied by lookup — the
        plurality map on the full-range pass (``year=None``), the year's slice map on a
        per-year pass — never via ``community.detect``.
        """
        strategy_results: dict[str, tuple] = {}
        detection_graph: "nx.DiGraph | None" = None
        detect_on = graph
        backbone_alpha = options.get("community_backbone_alpha") or 0.0
        self.stdout.write("Calculate communities")
        self.stdout.flush()
        if backbone_alpha and communities_strategy:
            detection_graph = disparity_filter(graph, backbone_alpha)
            detect_on = detection_graph
            self.stdout.write(
                f"- disparity-filter backbone (α={backbone_alpha:g}) … "
                f"{detection_graph.number_of_edges()}/{graph.number_of_edges()} edges kept"
            )
            self.stdout.flush()
        # CONSENSUS aggregates the other strategies' partitions and LEIDEN_TEMPORAL is precomputed
        # over the timeline slices, so both are dispatched outside the direct loop — their position
        # in the ordered token list only affects display order, never compute order.
        _special = {"CONSENSUS", "LEIDEN_TEMPORAL"}
        direct = [inst for inst in communities_strategy if inst.name not in _special]
        temporal_instances = [inst for inst in communities_strategy if inst.name == "LEIDEN_TEMPORAL"]
        consensus_instances = [inst for inst in communities_strategy if inst.name == "CONSENSUS"]
        for instance in direct:
            self.stdout.write(f"- {instance.label} … ", ending="")
            self.stdout.flush()
            try:
                # The parameterised strategy (LEIDEN_CPM γ) reads its tunable value
                # from the instance; the global flags only seed bare-token defaults at parse time.
                community_map, community_palette = community.detect(
                    instance,
                    options["community_palette"],
                    detect_on,
                    channel_dict,
                    reverse=options["community_palette_reversed"],
                )
            except ValueError as e:
                raise CommandError(str(e)) from e
            community.apply_to_graph(graph, channel_dict, community_map, community_palette, instance)
            strategy_results[instance.key] = (community_map, community_palette)
            n_communities = len(set(community_map.values()))
            self.stdout.write(f"{n_communities} communities")
            self.stdout.flush()
        for instance in temporal_instances:
            entry = (temporal_results or {}).get(instance.key)
            self.stdout.write(f"- {instance.label} … ", ending="")
            self.stdout.flush()
            if entry is None:
                # Defensive: validation + precompute run before any _compute_communities call,
                # so a missing entry means the precompute was skipped upstream.
                self.stdout.write(self.style.WARNING("skipped (no temporal precompute available)"))
                continue
            per_year_maps, plurality_map, community_palette = entry
            if year is None:
                community_map = plurality_map
                note = f" (plurality across {len(per_year_maps)} slices)"
            else:
                # A year that exports successfully was built with the same arguments as its
                # temporal slice, so the map exists; guard anyway rather than KeyError.
                community_map = per_year_maps.get(year, {})
                note = "" if year in per_year_maps else " (year missing from temporal slices)"
            community.apply_to_graph(graph, channel_dict, community_map, community_palette, instance)
            strategy_results[instance.key] = (community_map, community_palette)
            n_communities = len(set(community_map.values()))
            self.stdout.write(f"{n_communities} communities{note}")
            self.stdout.flush()
        for instance in consensus_instances:
            input_maps = {
                inst.key: strategy_results[inst.key][0]
                for inst in direct
                if community.consensus_eligible(inst.name) and inst.key in strategy_results
            }
            self.stdout.write(f"- {instance.label} … ", ending="")
            self.stdout.flush()
            try:
                community_map, community_palette = community.detect_consensus(
                    detect_on,
                    options["community_palette"],
                    input_maps,
                    float(instance.params_dict.get("threshold", community.CONSENSUS_DEFAULT_THRESHOLD)),
                    reverse=options["community_palette_reversed"],
                )
            except ValueError as e:
                raise CommandError(str(e)) from e
            community.apply_to_graph(graph, channel_dict, community_map, community_palette, instance)
            strategy_results[instance.key] = (community_map, community_palette)
            n_communities = len(set(community_map.values()))
            self.stdout.write(f"{n_communities} communities (from {len(input_maps)} partitions)")
            self.stdout.flush()
        community.apply_edge_colors(graph, edge_list, channel_dict)
        return strategy_results, detection_graph

    def _compute_layout(
        self,
        graph: nx.DiGraph,
        do_graph: bool,
        do_3dgraph: bool,
        fa2_iterations: str | int,
        target_layout: str,
        reference_positions: "dict | None" = None,
        reference_positions_3d: "dict | None" = None,
    ) -> tuple[dict, dict | None]:
        """Compute 2D (and optionally 3D) ForceAtlas2 positions.

        When *reference_positions* / *reference_positions_3d* are supplied
        (full-range layout) the per-year export skips the independent
        Kamada-Kawai run and seeds FA2 from the reference instead, running KK
        only for nodes absent from the reference.  For 2D the orientation is
        also corrected via discrete 90°-rotation alignment.
        """
        positions_3d: dict | None = None
        if not (do_graph or do_3dgraph):
            return {}, None

        # Resolve "Nx" multiplier form to a concrete iteration count using the
        # current graph's node count (floored at 100).
        fa2_iterations = layout.resolve_iterations(fa2_iterations, graph.number_of_nodes())

        self.stdout.write("\nSet spatial distribution of nodes")

        if reference_positions is not None:
            # Seed FA2 from the full-range layout so each year starts from the
            # same orientation.  KK is only computed for nodes absent from the
            # reference (channels that first appear in this specific year).
            new_nodes = [n for n in graph.nodes() if n not in reference_positions]
            if new_nodes:
                self.stdout.write(f"- Kamada-Kawai ({len(new_nodes)} new nodes) … ", ending="")
                self.stdout.flush()
                kk_pos = layout.kamada_kawai_positions(graph)
                initial_pos = {n: reference_positions.get(n, kk_pos[n]) for n in graph.nodes()}
                self.stdout.write("done")
            else:
                self.stdout.write("- seeding from reference layout … ", ending="")
                self.stdout.flush()
                initial_pos = {n: reference_positions[n] for n in graph.nodes()}
                self.stdout.write("done")
        else:
            self.stdout.write("- Kamada-Kawai … ", ending="")
            self.stdout.flush()
            initial_pos = layout.kamada_kawai_positions(graph)
            self.stdout.write("done")

        self.stdout.write(f"- ForceAtlas2 ({fa2_iterations} iterations) … ", ending="")
        self.stdout.flush()
        positions = layout.forceatlas2_positions(graph, initial_pos, fa2_iterations)
        self.stdout.write("done")

        if reference_positions is not None:
            # Align orientation to the reference using the best of the four
            # axis-aligned rotations (avoids drift introduced by FA2).
            self.stdout.write("- aligning orientation … ", ending="")
            positions = layout.align_to_reference(positions, reference_positions)
            self.stdout.write("done")
        else:
            # Full-range export: apply the existing aspect-ratio heuristic.
            xs, ys = zip(*positions.values(), strict=False)
            width = max(xs) - min(xs)
            height = max(ys) - min(ys)
            if (target_layout == layout.LAYOUT_HORIZONTAL and height > width) or (
                target_layout == layout.LAYOUT_VERTICAL and width > height
            ):
                self.stdout.write("- rotating layout 90° … ", ending="")
                self.stdout.flush()
                positions = layout.rotate_positions(positions)
                self.stdout.write("done")

        if do_3dgraph:
            if reference_positions_3d is not None:
                new_nodes_3d = [n for n in graph.nodes() if n not in reference_positions_3d]
                if new_nodes_3d:
                    self.stdout.write(f"- Kamada-Kawai 3D ({len(new_nodes_3d)} new nodes) … ", ending="")
                    self.stdout.flush()
                    kk_pos_3d = layout.kamada_kawai_positions_3d(graph)
                    initial_pos_3d = {n: reference_positions_3d.get(n, kk_pos_3d[n]) for n in graph.nodes()}
                    self.stdout.write("done")
                else:
                    self.stdout.write("- seeding 3D from reference layout … ", ending="")
                    self.stdout.flush()
                    initial_pos_3d = {n: reference_positions_3d[n] for n in graph.nodes()}
                    self.stdout.write("done")
            else:
                self.stdout.write("- Kamada-Kawai 3D … ", ending="")
                self.stdout.flush()
                initial_pos_3d = layout.kamada_kawai_positions_3d(graph)
                self.stdout.write("done")
            self.stdout.write(f"- ForceAtlas2 3D ({fa2_iterations} iterations) … ", ending="")
            self.stdout.flush()
            positions_3d = layout.forceatlas2_positions_3d(graph, initial_pos_3d, fa2_iterations)
            self.stdout.write("done")

        return positions, positions_3d

    def _compute_measures(
        self,
        graph: nx.DiGraph,
        graph_data: GraphData,
        channel_dict: dict,
        measure_instances: "list[measures.MeasureInstance]",
        start_date: datetime.date | None,
        end_date: datetime.date | None,
        do_graph: bool,
        do_3dgraph: bool,
        strategy_instances: "list[community.StrategyInstance] | None" = None,
    ) -> list[tuple[str, str]]:
        """Compute every requested measure instance in order, returning suffixed (key, label) pairs.

        Each instance is dispatched to its ``apply_*`` function with its own parameters; the bare
        node keys it writes are then rebound to parameter-suffixed keys (:func:`_rebind_measure_keys`)
        so a measure requested more than once (e.g. two DIFFUSIONLAG windows) keeps distinct
        columns. HITS is computed at most once.
        """
        self.stdout.write("\nCalculations on the graph")
        self.stdout.write("- largest component … ", ending="")
        self.stdout.flush()
        main_component_nodes = exporter.find_main_component(graph)
        self.stdout.write(f"{len(main_component_nodes)} nodes")

        self.stdout.write("- degrees, activity and fans")
        measures_labels = measures.apply_base_node_measures(
            graph_data, graph, channel_dict, start_date=start_date, end_date=end_date
        )

        # Ordered community-partition keys present on the nodes, in *selection order* —
        # a family basis must resolve to the first selected instance. Per-node
        # accretion would instead depend on which node iterates first (a LABELGROUP
        # partition is absent from unassigned nodes, so a dead leaf at the front of the
        # dict would demote it behind the algorithmic partitions).
        present_keys: set[str] = set()
        for _nid, node_data in graph.nodes(data="data"):
            if node_data and node_data.get("communities"):
                present_keys.update(node_data["communities"])
        available_bases = [si.key for si in (strategy_instances or []) if si.key in present_keys]
        # Defensive: node keys outside the selection (shouldn't happen) go last, sorted.
        available_bases += sorted(present_keys - set(available_bases))

        step_fn = {key: fn for key, _label, fn in measures.MEASURE_STEPS}
        hits_computed = False
        hits_labels: list[tuple[str, str]] = []
        resolved_seen: set[str] = set()

        for inst in measure_instances:
            m = inst.measure
            resolved = inst
            # Resolve the community basis up-front for partition-based measures so we can skip
            # cleanly (and label the progress line / output columns with the concrete basis).
            if m == "MODULEROLE":
                basis = _resolve_community_basis(inst, available_bases)
                if basis is None:
                    self.stdout.write(
                        self.style.WARNING(f"- {_MEASURE_PROGRESS[m]} … skipped (no community partition)")
                    )
                    continue
                resolved = inst.resolved_with(basis=basis.upper())
                # A bare MODULEROLE auto-resolves to the same basis an explicit
                # instance may already name; the two would emit identical suffixed
                # columns twice. Parse-time dedup can't see this (it runs before
                # basis resolution), so it is enforced here.
                if resolved.token() in resolved_seen:
                    self.stdout.write(
                        self.style.WARNING(
                            f"- {_MEASURE_PROGRESS[m]}{resolved.label_annotation()} … "
                            "skipped (duplicate after basis resolution)"
                        )
                    )
                    continue
                resolved_seen.add(resolved.token())

            self.stdout.write(f"- {_MEASURE_PROGRESS.get(m, m.lower())}{resolved.label_annotation()} … ", ending="")
            self.stdout.flush()

            if m in step_fn:
                labels = getattr(measures, step_fn[m])(graph_data, graph)
            elif m == "AMPLIFICATION":
                labels = measures.apply_amplification_factor(
                    graph_data, graph, channel_dict, start_date=start_date, end_date=end_date
                )
            elif m == "CONTENTORIGINALITY":
                labels = measures.apply_content_originality(
                    graph_data, graph, channel_dict, start_date=start_date, end_date=end_date
                )
            elif m == "DIFFUSIONLAG":
                labels = measures.apply_diffusion_lag(
                    graph_data,
                    graph,
                    channel_dict,
                    start_date=start_date,
                    end_date=end_date,
                    window_days=resolved.params_dict["window"],
                )
            elif m in ("HITSHUB", "HITSAUTH"):
                if not hits_computed:
                    # Writes both hub and authority on every node; returns [] when the
                    # computation failed (degenerate graph) and no keys were written.
                    hits_labels = measures.apply_hits(graph_data, graph)
                    hits_computed = True
                wanted = "hits_hub" if m == "HITSHUB" else "hits_authority"
                labels = [(key, label) for key, label in hits_labels if key == wanted]
                if not labels:
                    self.stdout.write(self.style.WARNING("skipped (HITS could not be computed)"))
                    continue
            elif m == "MODULEROLE":
                labels = measures.apply_module_role(graph_data, graph, resolved.params_dict["basis"].lower())
            else:  # defensive — parse_measures already rejected unknown tokens
                self.stdout.write(self.style.WARNING("unknown measure, skipped"))
                continue

            measures_labels += _rebind_measure_keys(graph_data, resolved, labels)
            self.stdout.write("done")

        if do_graph or do_3dgraph:
            self.stdout.write("- small components")
            exporter.reposition_isolated_nodes(graph_data, main_component_nodes)

        return measures_labels

    def _compute_temporal_partitions(
        self,
        opts: ResolvedOptions,
        temporal_instances: "list[community.StrategyInstance]",
    ) -> dict[str, tuple]:
        """Precompute every LEIDEN_TEMPORAL instance over the per-year timeline slices.

        Builds one graph per timeline year with exactly the arguments ``_run_year_export`` will
        use (so slices and year exports always agree), applies the ``--community-backbone-alpha``
        filter when set (matching what per-year detection would see), and runs
        :func:`community.detect_leiden_temporal` per instance. Returns
        ``{instance.key: (per_year_maps, plurality_map, palette)}`` for
        ``_compute_communities`` to apply by lookup. Raises ``CommandError`` when fewer than two
        years yield a non-empty graph — the coupling needs at least two slices.
        """
        year_range = _timeline_year_range(opts.start_date, opts.end_date)
        years = list(range(year_range[0], year_range[1] + 1)) if year_range else []
        self.stdout.write("Temporal community slices")
        year_graphs: dict[int, nx.DiGraph] = {}
        for year in years:
            start_date, end_date = _clamp_year_window(year, opts.start_date, opts.end_date)
            try:
                year_graph, _, _, _ = graph_builder.build_graph(
                    draw_dead_leaves=opts.draw_dead_leaves,
                    dead_leaves_color=opts.dead_leaves_color,
                    start_date=start_date,
                    end_date=end_date,
                    channel_types=opts.channel_types,
                    channel_sources=opts.channel_sources or None,
                    edge_weight_strategy=opts.edge_weight_strategy,
                    include_mentions=opts.include_mentions,
                    include_self_references=opts.include_self_references,
                    include_lost=opts.include_lost,
                    include_private=opts.include_private,
                )
            except ValueError:
                continue  # year without relationships — no slice, matching the year loop's skip
            if not year_graph.nodes:
                continue
            if opts.community_backbone_alpha:
                year_graph = disparity_filter(year_graph, opts.community_backbone_alpha)
            year_graphs[year] = year_graph
        self.stdout.write(f"- {len(year_graphs)} usable year slices ({', '.join(map(str, sorted(year_graphs)))})")
        temporal_results: dict[str, tuple] = {}
        for instance in temporal_instances:
            self.stdout.write(f"- {instance.label} … ", ending="")
            self.stdout.flush()
            params = instance.params_dict
            try:
                per_year, plurality, palette = community.detect_leiden_temporal(
                    year_graphs,
                    opts.community_palette,
                    float(params.get("resolution", community.CPM_DEFAULT_RESOLUTION)),
                    float(params.get("interslice", community.TEMPORAL_DEFAULT_INTERSLICE)),
                    reverse=opts.community_palette_reversed,
                )
            except ValueError as e:
                raise CommandError(str(e)) from e
            temporal_results[instance.key] = (per_year, plurality, palette)
            n_communities = len({cid for cmap in per_year.values() for cid in cmap.values()})
            self.stdout.write(f"{n_communities} communities across {len(per_year)} slices")
            self.stdout.flush()
        return temporal_results

    def _run_year_export(
        self,
        year: int,
        root_target: str,
        options: dict,
        measure_instances: "list[measures.MeasureInstance]",
        communities_strategy: list[str],
        strategies: list[str],
        do_graph: bool,
        do_3dgraph: bool,
        do_xlsx: bool,
        channel_types: list[str],
        channel_sources: list[str],
        edge_weight_strategy: str,
        fa2_iterations: int,
        target_layout: str,
        seo: bool,
        project_title: str,
        selected_network_groups: "frozenset[str]",
        reference_positions: dict | None = None,
        reference_positions_3d: dict | None = None,
        extra_layout_names: list[str] | None = None,
        extra_layout_names_3d: list[str] | None = None,
        do_robustness: bool = False,
        robustness_alpha: float = 0.05,
        robustness_strategies: list[str] | None = None,
        robustness_runs: int = 100,
        robustness_null: int = 20,
        robustness_seed: int = 42,
        robustness_sample: int = 500,
        do_interest_structural: bool = False,
        interest_window_days: int = 30,
        interest_include_mentions: bool = False,
        do_coordination: bool = False,
        do_coordination_3d: bool = False,
        coordination_window: int = 300,
        coordination_min_events: int = 3,
        coord_reference_positions: dict | None = None,
        coord_reference_positions_3d: dict | None = None,
        window_start: datetime.date | None = None,
        window_end: datetime.date | None = None,
        temporal_results: "dict[str, tuple] | None" = None,
    ) -> dict | None:
        """Run the full export pipeline for a single calendar year and write per-year files."""
        # Clamp the calendar year to the user's --startdate/--enddate window so a
        # windowed run does not emit graphs for the out-of-window part of a year.
        start_date, end_date = _clamp_year_window(year, window_start, window_end)

        self.stdout.write(f"\n  {year} … ", ending="")
        self.stdout.flush()

        try:
            graph, channel_dict, edge_list, channel_qs = graph_builder.build_graph(
                draw_dead_leaves=options["draw_dead_leaves"],
                dead_leaves_color=options.get("dead_leaves_color"),
                start_date=start_date,
                end_date=end_date,
                channel_types=channel_types,
                channel_sources=channel_sources or None,
                edge_weight_strategy=edge_weight_strategy,
                include_mentions=options["include_mentions"],
                include_self_references=options["include_self_references"],
                include_lost=options["include_lost"],
                include_private=options["include_private"],
            )
        except ValueError as e:
            self.stdout.write(self.style.WARNING(f"skipped ({e})"))
            return None

        if not graph.nodes:
            self.stdout.write(self.style.WARNING("skipped (empty graph)"))
            return None

        n_nodes, n_edges = len(graph.nodes), len(graph.edges)
        self.stdout.write(f"{n_nodes} nodes, {n_edges} edges")

        strategy_results, detection_graph = self._compute_communities(
            graph, channel_dict, edge_list, communities_strategy, options, temporal_results=temporal_results, year=year
        )
        positions, positions_3d = self._compute_layout(
            graph,
            do_graph,
            do_3dgraph,
            fa2_iterations,
            target_layout,
            reference_positions,
            reference_positions_3d,
        )

        year_extra_positions: dict[str, dict] = {}
        year_extra_positions_3d: dict[str, dict] = {}
        if do_graph and extra_layout_names:
            year_extra_positions = _compute_extra_layouts(
                graph, extra_layout_names, dim=2, strategy_results=strategy_results
            )
        if do_3dgraph and extra_layout_names_3d:
            year_extra_positions_3d = _compute_extra_layouts(graph, extra_layout_names_3d, dim=3)

        self.stdout.write("\nBuild graph data … ", ending="")
        self.stdout.flush()
        graph_data = exporter.build_graph_data(graph, positions)
        self.stdout.write("done")
        measures_labels = self._compute_measures(
            graph,
            graph_data,
            channel_dict,
            measure_instances,
            start_date,
            end_date,
            do_graph,
            do_3dgraph,
            strategy_instances=communities_strategy,
        )

        communities_data = community.build_communities_payload(communities_strategy, strategy_results)
        community_table_data = None

        with tempfile.TemporaryDirectory() as tmp_dir:
            exporter.write_graph_files(
                graph_data,
                communities_data,
                measures_labels,
                channel_qs,
                graph_dir=tmp_dir,
                include_positions=do_graph or do_3dgraph,
                positions_3d=positions_3d,
                extra_positions=year_extra_positions or None,
                extra_positions_3d=year_extra_positions_3d or None,
            )
            exporter.write_meta_json(
                graph_dir=tmp_dir,
                project_title=project_title,
                edge_weight_strategy=edge_weight_strategy,
                start_date=start_date,
                end_date=end_date,
                total_nodes=n_nodes,
                total_edges=n_edges,
                community_distribution_threshold=options["community_distribution_threshold"],
                has_consensus_matrix=False,
                community_backbone_alpha=options.get("community_backbone_alpha") or 0.0,
            )
            community_table_data = community_stats.compute_community_metrics(
                graph_data,
                communities_data,
                graph,
                strategies,
                measures_labels=measures_labels,
                status_callback=None,
                channel_qs=channel_qs,
                start_date=start_date,
                end_date=end_date,
                selected_network_groups=selected_network_groups,
                detection_graph=detection_graph,
            )
            tables.write_network_metrics_json(community_table_data, strategies, graph_dir=tmp_dir)
            tables.write_community_metrics_json(community_table_data, strategies, graph_dir=tmp_dir)

            rob_payload: dict | None = None
            if do_robustness:
                rob_partitions: dict = {}
                for inst in communities_strategy:
                    cmap = strategy_results[inst.key][0]
                    if len(set(cmap.values())) > 1:
                        rob_partitions[inst.key] = cmap
                rob_payload = robustness.run_robustness(
                    graph,
                    partitions=rob_partitions or None,
                    config=robustness.RobustnessConfig(
                        alpha=robustness_alpha,
                        strategies=list(robustness_strategies) if robustness_strategies else None,
                        n_random_runs=robustness_runs,
                        n_null=robustness_null,
                        seed=robustness_seed,
                        reach_sample=robustness_sample,
                    ),
                )
                exporter.write_robustness_json(rob_payload, graph_dir=tmp_dir)

            if do_interest_structural:
                year_window_filter = _date_window_filter(start_date, end_date)
                year_qs = Message.objects.alive().filter(**year_window_filter)
                year_score_map = scoring.score_messages_for_window(year_qs)
                year_int_payload = interest_structural.compute_interest_structural(
                    graph_data,
                    channel_dict,
                    community_strategy=_pick_interest_community_strategy(communities_strategy),
                    authority_key=_pick_interest_authority_key({i.measure for i in measure_instances}),
                    window_days=interest_window_days,
                    include_mentions=interest_include_mentions,
                    window_filter=year_window_filter,
                    interest_score_override=year_score_map,
                )
                exporter.write_interest_structural_json(year_int_payload, graph_dir=tmp_dir)

            year_data_dst = os.path.join(root_target, f"data_{year}")
            if os.path.exists(year_data_dst):
                shutil.rmtree(year_data_dst)
            shutil.move(os.path.join(tmp_dir, "data"), year_data_dst)

        # Per-year coordination layer: same thresholds as the full range, seeded
        # from the full-range coordination layout so years keep a stable
        # orientation (mirroring the reference-seeding scheme of the main map).
        # A year's ties are a subset of the full range's (counts only grow with
        # a wider window), so the reference covers every per-year node; the
        # Kamada-Kawai fallback below is defensive only.
        has_coordination = False
        coordination_nodes = 0
        coordination_ties = 0
        if do_coordination:
            coord_result = coordination.compute_coordination(
                [int(cid) for cid in channel_dict],
                start_date=start_date,
                end_date=end_date,
                window_seconds=coordination_window,
                min_events=coordination_min_events,
            )
            if coord_result.edges:
                co_graph = coordination.build_nx_graph(coord_result, graph)
                co_iterations = layout.resolve_iterations(fa2_iterations, co_graph.number_of_nodes())
                ref = coord_reference_positions or {}
                if any(n not in ref for n in co_graph.nodes()):
                    kk = layout.kamada_kawai_positions(co_graph)
                    initial = {n: ref.get(n, kk[n]) for n in co_graph.nodes()}
                else:
                    initial = {n: ref[n] for n in co_graph.nodes()}
                co_positions = layout.forceatlas2_positions(co_graph, initial, co_iterations)
                if ref:
                    co_positions = layout.align_to_reference(co_positions, ref)
                co_positions_3d = None
                if do_coordination_3d:
                    ref_3d = coord_reference_positions_3d or {}
                    if any(n not in ref_3d for n in co_graph.nodes()):
                        kk_3d = layout.kamada_kawai_positions_3d(co_graph)
                        initial_3d = {n: ref_3d.get(n, kk_3d[n]) for n in co_graph.nodes()}
                    else:
                        initial_3d = {n: ref_3d[n] for n in co_graph.nodes()}
                    co_positions_3d = layout.forceatlas2_positions_3d(co_graph, initial_3d, co_iterations)
                coord_graph_data = exporter.build_coordination_graph_data(graph_data, coord_result, co_positions)
                exporter.write_coordination_files(
                    coord_graph_data,
                    co_positions_3d,
                    coordination.coordination_measures_labels(),
                    root_target,
                    communities_data=communities_data,
                    dir_name=f"data_coordination_{year}",
                )
                has_coordination = True
                coordination_nodes = len(coord_graph_data["nodes"])
                coordination_ties = len(coord_result.edges)

        # Per-year XLSX files are not written individually; data is returned so the
        # caller can assemble a single multi-sheet workbook for each table type.
        return {
            "year": year,
            "nodes": n_nodes,
            "edges": n_edges,
            "has_graph": True,
            "has_channel_html": True,
            "has_network_html": True,
            "has_community_html": True,
            "has_robustness": do_robustness and rob_payload is not None,
            "has_coordination": has_coordination,
            "coordination_nodes": coordination_nodes,
            "coordination_ties": coordination_ties,
            # Returned to the caller so it can assemble multi-sheet XLSX workbooks.
            "_xlsx_graph_data": graph_data if do_xlsx else None,
            "_xlsx_community_data": community_table_data if do_xlsx else None,
            "_xlsx_robustness_data": rob_payload if (do_xlsx and rob_payload is not None) else None,
        }

    def _resolve_options(self, options: dict[str, Any]) -> ResolvedOptions:
        """Parse CSV/date options into a typed bundle.

        A bare `python manage.py structural_analysis` (no flags) must do
        nothing. The CLI therefore no longer consults `settings.SA_*` for
        fallbacks — missing flags resolve to typed no-op literals (False
        for toggles, `[]` for lists, `""` for strings, `0` / `0.0` for
        numerics). Tuning constants whose feature is opted into elsewhere
        (Leiden CPM resolution, vacancy / robustness numerics,
        diffusion window) keep their hardcoded sensible
        defaults — they're parameters of features the user enables, not
        feature toggles themselves.

        Panel-driven runs are unaffected: the Operations panel emits
        explicit `--<flag>` / `--no-<flag>` for every checkbox (bool_explicit),
        so the form's state always rides through the args dict.
        """

        def _o(key: str, default: Any) -> Any:
            v = options[key]
            return v if v is not None else default

        raw_community_strategies = _parse_csv(_o("community_strategies", ""))
        # The deprecated --leiden-coarse/fine-resolution flags still seed the bare-LEIDEN_CPM default
        # for one release (coarse preferred); prefer --leiden-cpm-resolution or LEIDEN_CPM(resolution=…).
        leiden_cpm_resolution = _o("leiden_cpm_resolution", None)
        if leiden_cpm_resolution is None:
            leiden_cpm_resolution = options.get("leiden_coarse_resolution") or options.get("leiden_fine_resolution")
        if leiden_cpm_resolution is None:
            leiden_cpm_resolution = community.CPM_DEFAULT_RESOLUTION
        # Parse into ordered StrategyInstance objects (handles ALL, keyword params, duplicate
        # detection); a bare LEIDEN_CPM inherits the resolved global default above.
        try:
            communities_strategy = community.parse_strategies(
                raw_community_strategies,
                defaults={
                    "LEIDEN_CPM": {"resolution": leiden_cpm_resolution},
                },
            )
        except ValueError as exc:
            raise CommandError(f"--community-strategies: {exc}") from exc
        raw_network_measures = _parse_csv(_o("measures", ""))
        # Parse into ordered MeasureInstance objects (handles ALL, keyword params, duplicate
        # detection). A paren-less DIFFUSIONLAG inherits the global --diffusion-window as its
        # default parameter value.
        try:
            measure_instances = measures.parse_measures(
                raw_network_measures,
                defaults={
                    "DIFFUSIONLAG": {"window": _o("diffusion_window", 30)},
                },
            )
        except ValueError as exc:
            raise CommandError(f"--measures: {exc}") from exc
        raw_network_stat_groups = _parse_csv(_o("network_stat_groups", ""))
        network_stat_groups = (
            measures.ALL_NETWORK_STAT_GROUPS if "ALL" in raw_network_stat_groups else raw_network_stat_groups
        )
        channel_types_raw = options["channel_types"]
        # No --channel-types on a bare CLI run resolves to the built-in default rather than
        # an empty list, which channel_type_filter([]) would match against nothing (→ a
        # graph with no channels and the misleading "no relationships between channels").
        channel_types = (
            _parse_csv(channel_types_raw) if channel_types_raw is not None else list(settings.DEFAULT_CHANNEL_TYPES)
        )
        channel_sources_raw = options["channel_sources"]
        # Case-preserving (NOT _parse_csv): ChannelSource.key is a lowercase slug and
        # sources__key__in matches case-sensitively — upper-casing would select zero
        # channels for every source. crawl_channels parses this flag the same way.
        channel_sources = (
            [s.strip() for s in channel_sources_raw.split(",") if s.strip()] if channel_sources_raw else []
        )
        # Fall back to the config-derived strategy (settings.SA_EDGE_WEIGHT_STRATEGY) when
        # no --edge-weight-strategy is passed, then to the documented default. An empty
        # value would otherwise reach build_graph and silently zero every edge weight
        # (the PARTIAL_REFERENCES branch only fills referencing_counts for the exact token).
        edge_weight_strategy: str = _o("edge_weight_strategy", settings.SA_EDGE_WEIGHT_STRATEGY) or "PARTIAL_REFERENCES"
        _raw_vacancy = _o("vacancy_measures", "")
        raw_vacancy_measures = _parse_csv(_raw_vacancy) if _raw_vacancy else []
        selected_vacancy_measures = (
            set(vacancy_analysis.ALL_VACANCY_MEASURES) if "ALL" in raw_vacancy_measures else set(raw_vacancy_measures)
        )
        self._validate_settings(
            communities_strategy,
            measure_instances,
            network_stat_groups,
            channel_types,
            edge_weight_strategy,
            list(selected_vacancy_measures),
            do_interest_structural=_o("interest_structural", False),
        )

        # Robustness strategies — parse, validate, expand ALL.
        _raw_rob = _o("robustness_strategies", "")
        _raw_rob_tokens = _parse_csv(_raw_rob) if _raw_rob else []
        if "ALL" in _raw_rob_tokens:
            robustness_strategies = list(robustness.ALL_STRATEGIES)
        else:
            robustness_strategies = [t.lower() for t in _raw_rob_tokens]
        for token in robustness_strategies:
            try:
                robustness.parse_strategy(token)
            except ValueError as exc:
                raise CommandError(f"--robustness-strategies: {exc}") from exc
        # Selecting strategies selects the analysis (the Operations panel emits
        # --robustness alongside the list for the same reason): validating a strategy
        # list and then silently discarding it would look like the analysis ran.
        # An explicit --robustness/--no-robustness still wins over the implication.
        if options["robustness"] is not None:
            do_robustness = options["robustness"]
        else:
            do_robustness = _o("robustness", False) or bool(robustness_strategies)
        if do_robustness and not robustness_strategies:
            robustness_strategies = list(robustness.DEFAULT_STRATEGIES)

        extra_layout_names = _parse_csv(_o("layouts_2d", ""))
        if "ALL" in extra_layout_names:
            extra_layout_names = sorted(layout.EXTRA_LAYOUT_CHOICES_2D)
        # Reject unknown tokens like every other token flag — silently filtering a
        # misspelled layout would just drop it from the export's layout switcher.
        _unknown_2d = [n for n in extra_layout_names if n not in layout.EXTRA_LAYOUT_CHOICES_2D]
        if _unknown_2d:
            raise CommandError(
                f"--layouts-2d: unknown layout(s) {', '.join(_unknown_2d)}. "
                f"Choose from {sorted(layout.EXTRA_LAYOUT_CHOICES_2D)} or ALL."
            )

        extra_layout_names_3d = _parse_csv(_o("layouts_3d", ""))
        if "ALL" in extra_layout_names_3d:
            extra_layout_names_3d = sorted(layout.EXTRA_LAYOUT_CHOICES_3D)
        _unknown_3d = [n for n in extra_layout_names_3d if n not in layout.EXTRA_LAYOUT_CHOICES_3D]
        if _unknown_3d:
            raise CommandError(
                f"--layouts-3d: unknown layout(s) {', '.join(_unknown_3d)}. "
                f"Choose from {sorted(layout.EXTRA_LAYOUT_CHOICES_3D)} or ALL."
            )

        # Community-detection backbone — 0 disables; α in (0, 1) filters. 1 keeps every edge
        # (the disparity test is a strict <), so it is rejected as a likely typo rather than
        # silently running an unfiltered "backbone".
        community_backbone_alpha = _o("community_backbone_alpha", 0.0)
        if not (0.0 <= community_backbone_alpha < 1.0):
            raise CommandError(
                f"--community-backbone-alpha must be 0 (off) or in (0, 1); got {community_backbone_alpha!r}."
            )

        # LEIDEN_TEMPORAL couples the per-year timeline slices — without a year timeline there is
        # nothing to couple, so fail before any heavy work rather than in the export phase.
        timeline_step = _o("timeline_step", "none")
        if any(i.name == "LEIDEN_TEMPORAL" for i in communities_strategy) and timeline_step != "year":
            raise CommandError(
                "LEIDEN_TEMPORAL requires --timeline-step year: it couples the per-year timeline "
                "slices into one temporal partition. Enable the timeline, or drop the strategy."
            )

        # Coordination analysis — plain numeric parameters of an opt-in feature.
        coordination_window = _o("coordination_window", coordination.DEFAULT_WINDOW_SECONDS)
        coordination_min_events = _o("coordination_min_events", coordination.DEFAULT_MIN_EVENTS)
        if coordination_window < 1:
            raise CommandError("--coordination-window must be at least 1 second.")
        if coordination_min_events < 1:
            raise CommandError("--coordination-min-events must be at least 1.")

        vertical = _o("vertical_layout", False)
        export_name = re.sub(r"[^\w\-]", "-", (options.get("name") or "").strip()).strip("-")
        if not export_name:
            export_name = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")

        # An explicit --community-palette wins; otherwise fall back to the config-derived
        # palette (and its reversed flag). A bare CLI run with no config would otherwise
        # resolve to "" and reach community.detect() as "palette '' not found".
        palette_opt = options["community_palette"]
        if palette_opt is not None:
            raw_palette = palette_opt
            reversed_default = False
        else:
            raw_palette = settings.COMMUNITY_PALETTE
            reversed_default = settings.COMMUNITY_PALETTE_REVERSED
        if raw_palette == "ORGANIZATION":
            # Legacy alias: the old default doubled as a "use organisation
            # colours for ORG, vaporwave-reversed for everything else" marker.
            # Map it explicitly here so a CLI override of "ORGANIZATION" works.
            raw_palette = "vaporwave"
            reversed_default = True
        elif not raw_palette:
            # Neither a flag nor a config palette: documented default — vaporwave,
            # reversed so the most-vivid colours land on the largest communities.
            raw_palette = "vaporwave"
            reversed_default = True
        if raw_palette and not is_known_palette(raw_palette):
            raise CommandError(
                f"Unknown --community-palette: {raw_palette!r}. Pick a name from the pypalettes catalogue."
            )
        community_palette = raw_palette
        community_palette_reversed = _o("community_palette_reversed", reversed_default)

        return ResolvedOptions(
            do_graph=_o("graph", False),
            do_3dgraph=_o("graph_3d", False),
            do_html=_o("html", False),
            do_xlsx=_o("xlsx", False),
            do_gexf=_o("gexf", False),
            do_graphml=_o("graphml", False),
            do_csv=_o("csv", False),
            do_consensus_matrix=_o("consensus_matrix", False),
            do_structural_similarity=_o("structural_similarity", False),
            do_behavioural_equivalence=_o("behavioural_equivalence", False),
            seo=_o("seo", False),
            vertical_layout=vertical,
            target_layout=layout.LAYOUT_VERTICAL if vertical else layout.LAYOUT_HORIZONTAL,
            fa2_iterations=_o("fa2_iterations", ""),
            extra_layout_names=extra_layout_names,
            extra_layout_names_3d=extra_layout_names_3d,
            start_date=self._parse_date(options["startdate"], "--startdate"),
            end_date=self._parse_date(options["enddate"], "--enddate"),
            draw_dead_leaves=_o("draw_dead_leaves", False),
            dead_leaves_color=options.get("dead_leaves_color") or "",
            community_palette=community_palette,
            community_palette_reversed=community_palette_reversed,
            include_mentions=_o("include_mentions", False),
            include_self_references=_o("include_self_references", False),
            include_lost=_o("include_lost", False),
            include_private=_o("include_private", False),
            channel_types=channel_types,
            channel_sources=channel_sources,
            edge_weight_strategy=edge_weight_strategy,
            communities_strategy=communities_strategy,
            strategies_lower=[inst.key for inst in communities_strategy],
            community_backbone_alpha=community_backbone_alpha,
            measure_instances=measure_instances,
            selected_network_groups=frozenset(network_stat_groups),
            diffusion_window=_o("diffusion_window", 30),
            leiden_cpm_resolution=leiden_cpm_resolution,
            community_distribution_threshold=_o("community_distribution_threshold", 0),
            timeline_step=timeline_step,
            selected_vacancy_measures=selected_vacancy_measures,
            vacancy_months_before=_o("vacancy_months_before", 12),
            vacancy_months_after=_o("vacancy_months_after", 24),
            vacancy_max_candidates=_o("vacancy_max_candidates", 30),
            do_robustness=do_robustness,
            robustness_alpha=_o("robustness_alpha", 0.05),
            robustness_strategies=robustness_strategies,
            robustness_runs=_o("robustness_runs", 100),
            robustness_null=_o("robustness_null", 20),
            robustness_seed=_o("robustness_seed", 42),
            robustness_sample=_o("robustness_sample", 500),
            do_interest_structural=_o("interest_structural", False),
            interest_window_days=_o("interest_window_days", 30),
            interest_include_mentions=_o("interest_include_mentions", False),
            do_coordination_2d=_o("coordination_2d", False),
            do_coordination_3d=_o("coordination_3d", False),
            coordination_window=coordination_window,
            coordination_min_events=coordination_min_events,
            export_name=export_name,
        )

    def handle(self, *args: Any, **options: Any) -> None:
        # Route logger.warning/error lines (exporter, interest_structural, …)
        # through self.style so they carry severity colour in the Operations panel.
        with styled_warning_logs(self.style):
            self._handle(*args, **options)

    def _handle(self, *args: Any, **options: Any) -> None:
        opts = self._resolve_options(options)
        # Patch options dict so _run_year_export and _compute_communities (which still
        # take a plain dict) see the resolved values.
        options.update(opts.to_options_dict())

        # Bare-CLI no-op: every output / measure / strategy / network stat /
        # vacancy / robustness toggle is off. Bail out before building the
        # graph so a flag-less invocation does literally nothing.
        if not any(
            (
                opts.do_graph,
                opts.do_3dgraph,
                opts.do_html,
                opts.do_xlsx,
                opts.do_gexf,
                opts.do_graphml,
                opts.do_csv,
                opts.do_consensus_matrix,
                opts.do_structural_similarity,
                opts.do_behavioural_equivalence,
                opts.measure_instances,
                opts.communities_strategy,
                opts.selected_network_groups,
                opts.selected_vacancy_measures,
                opts.do_robustness,
                opts.do_interest_structural,
                opts.do_coordination,
            )
        ):
            self.stdout.write(
                "Nothing to do — no outputs, measures, communities, network stats, "
                "vacancy measures, or robustness were requested. Pass at least one flag."
            )
            return

        self.stdout.write("Create graph … ", ending="")
        self.stdout.flush()
        try:
            graph, channel_dict, edge_list, channel_qs = graph_builder.build_graph(
                draw_dead_leaves=opts.draw_dead_leaves,
                dead_leaves_color=opts.dead_leaves_color,
                start_date=opts.start_date,
                end_date=opts.end_date,
                channel_types=opts.channel_types,
                channel_sources=opts.channel_sources or None,
                edge_weight_strategy=opts.edge_weight_strategy,
                include_mentions=opts.include_mentions,
                include_self_references=opts.include_self_references,
                include_lost=opts.include_lost,
                include_private=opts.include_private,
            )
        except ValueError as e:
            raise CommandError(str(e)) from e
        self.stdout.write(f"{len(graph.nodes)} nodes, {len(graph.edges)} edges")
        self.stdout.flush()

        # LEIDEN_TEMPORAL is precomputed over every timeline year at once (its whole point is
        # coupling the slices), then applied by lookup — the plurality summary on this full-range
        # pass, each year's slice map inside the timeline loop below.
        temporal_instances = [i for i in opts.communities_strategy if i.name == "LEIDEN_TEMPORAL"]
        temporal_results: dict[str, tuple] = {}
        if temporal_instances:
            temporal_results = self._compute_temporal_partitions(opts, temporal_instances)

        strategy_results, detection_graph = self._compute_communities(
            graph, channel_dict, edge_list, opts.communities_strategy, options, temporal_results=temporal_results
        )
        positions, positions_3d = self._compute_layout(
            graph, opts.do_graph, opts.do_3dgraph, opts.fa2_iterations, opts.target_layout
        )

        fa2_in_2d = opts.do_graph and "FA2" in opts.extra_layout_names
        fa2_in_3d = opts.do_3dgraph and "FA2" in opts.extra_layout_names_3d

        def _progress_2d(name: str) -> None:
            self.stdout.write(f"- {name.lower()} … ", ending="")
            self.stdout.flush()

        extra_positions: dict[str, dict] = {}
        if opts.do_graph and opts.extra_layout_names:
            non_fa2 = [n for n in opts.extra_layout_names if n != "FA2"]
            if non_fa2:
                self.stdout.write("\nCompute extra 2D layouts")
                extra_positions = _compute_extra_layouts(
                    graph, non_fa2, dim=2, strategy_results=strategy_results, on_progress=_progress_2d
                )
                self.stdout.write("done")

        extra_positions_3d: dict[str, dict] = {}
        if opts.do_3dgraph and opts.extra_layout_names_3d:
            non_fa2_3d = [n for n in opts.extra_layout_names_3d if n != "FA2"]
            if non_fa2_3d:
                self.stdout.write("\nCompute extra 3D layouts")
                extra_positions_3d = _compute_extra_layouts(graph, non_fa2_3d, dim=3, on_progress=_progress_2d)
                self.stdout.write("done")

        self.stdout.write("\nBuild graph data … ", ending="")
        self.stdout.flush()
        graph_data = exporter.build_graph_data(graph, positions)
        self.stdout.write("done")
        measures_labels = self._compute_measures(
            graph,
            graph_data,
            channel_dict,
            opts.measure_instances,
            opts.start_date,
            opts.end_date,
            opts.do_graph,
            opts.do_3dgraph,
            strategy_instances=opts.communities_strategy,
        )

        _final_target = str(Path(settings.BASE_DIR) / "exports" / opts.export_name)
        # All writes go to the staging directory; it is renamed to _final_target only after
        # write_summary_json completes, making every live export atomically consistent.
        root_target = _final_target + ".tmp"
        _old_target = _final_target + ".old"
        # Crash-window recovery: a run killed between _atomic_publish's two renames
        # leaves no live directory while the previous good export survives as .old.
        # Restore it before any cleanup — deleting it here (and then failing later,
        # e.g. on an empty graph) would permanently lose the only published copy.
        if not os.path.isdir(_final_target) and os.path.isdir(_old_target):
            os.rename(_old_target, _final_target)
        shutil.rmtree(root_target, ignore_errors=True)  # clean up any interrupted previous run
        shutil.rmtree(_old_target, ignore_errors=True)  # clean up any orphaned backup
        project_title: str = Project.load().title
        self.stdout.write("Build communities data … ", ending="")
        self.stdout.flush()
        communities_data = community.build_communities_payload(opts.communities_strategy, strategy_results)
        self.stdout.write("done")
        strategies = opts.strategies_lower

        # Copy the map template (js/, css/, static assets) whenever any HTML page is being
        # generated, not just when a graph is requested — table pages and the structural
        # similarity matrix all reference the same local CSS/JS files.
        need_static_assets = (
            opts.do_graph
            or opts.do_3dgraph
            or opts.do_html
            or opts.do_consensus_matrix
            or opts.do_structural_similarity
            or opts.do_behavioural_equivalence
            or opts.do_vacancy
            or opts.do_robustness
            # interest_structural.html imports ./js/utils.js and css/tables.css from
            # the copied map assets, like the vacancy/robustness pages above.
            or opts.do_interest_structural
            # coordination.html / coordination3d.html reuse the map viewer JS/CSS.
            or opts.do_coordination
        )
        if need_static_assets:
            exporter.ensure_graph_root(root_target)

        if opts.do_graph or opts.do_3dgraph or opts.do_coordination:
            self.stdout.write("\nGenerate map")
            self.stdout.write("- config files")
            if opts.do_graph or opts.do_3dgraph:
                exporter.apply_robots_to_graph_html(
                    root_target,
                    opts.seo,
                    project_title=project_title,
                    include_3d=opts.do_3dgraph,
                    vertical_layout=opts.vertical_layout,
                    extra_layouts=(["fa2"] if fa2_in_2d else []) + list(extra_positions.keys()),
                    extra_layouts_3d=(["fa2"] if fa2_in_3d else []) + list(extra_positions_3d.keys()),
                    node_count=len(graph_data.get("nodes", [])),
                    edge_count=len(graph_data.get("edges", [])),
                    # Real names for the manual LABELGROUP<id> colour-by options in the viewer.
                    strategy_labels=community.labelgroup_display_labels(),
                )
            exporter.write_robots_txt(root_target, opts.seo)

        self.stdout.write("- data files")
        exporter.write_graph_files(
            graph_data,
            communities_data,
            measures_labels,
            channel_qs,
            graph_dir=root_target,
            include_positions=opts.do_graph or opts.do_3dgraph,
            positions_3d=positions_3d,
            extra_positions=extra_positions or None,
            extra_positions_3d=extra_positions_3d or None,
        )
        exporter.write_meta_json(
            graph_dir=root_target,
            project_title=project_title,
            edge_weight_strategy=opts.edge_weight_strategy,
            start_date=opts.start_date,
            end_date=opts.end_date,
            total_nodes=len(graph.nodes),
            total_edges=len(graph.edges),
            community_distribution_threshold=opts.community_distribution_threshold,
            has_consensus_matrix=opts.do_consensus_matrix,
            community_backbone_alpha=opts.community_backbone_alpha,
        )

        need_community_metrics = opts.do_html or opts.do_xlsx or opts.do_consensus_matrix
        if need_community_metrics:
            self.stdout.write("- community metrics")
            _steps = ["network"] + strategies
            _step_iter = iter(_steps)
            next(_step_iter)  # skip "network"; already announced below

            def _on_metrics_step(label: str) -> None:
                self.stdout.write("done")
                next_label = next(_step_iter, None)
                if next_label is not None:
                    sd = communities_data.get(next_label)
                    n = len(sd.get("groups") or []) if sd else 0
                    self.stdout.write(f"  - {next_label} ({n} communities) … ", ending="")
                    self.stdout.flush()

            self.stdout.write("  - network … ", ending="")
            self.stdout.flush()
            community_table_data = community_stats.compute_community_metrics(
                graph_data,
                communities_data,
                graph,
                strategies,
                measures_labels=measures_labels,
                status_callback=_on_metrics_step,
                channel_qs=channel_qs,
                start_date=opts.start_date,
                end_date=opts.end_date,
                selected_network_groups=opts.selected_network_groups,
                detection_graph=detection_graph,
            )
            tables.write_network_metrics_json(community_table_data, strategies, graph_dir=root_target)
            tables.write_community_metrics_json(community_table_data, strategies, graph_dir=root_target)
        if opts.do_html:
            self.stdout.write("- table (html)")
            tables.write_table_html(
                graph_data,
                output_filename=os.path.join(root_target, "channel_table.html"),
                seo=opts.seo,
                project_title=project_title,
            )
            self.stdout.write("- network table (html)")
            tables.write_network_table_html(
                output_filename=os.path.join(root_target, "network_table.html"),
                seo=opts.seo,
                project_title=project_title,
            )
            self.stdout.write("- community table (html)")
            tables.write_community_table_html(
                output_filename=os.path.join(root_target, "community_table.html"),
                seo=opts.seo,
                project_title=project_title,
            )
        # XLSX written after the timeline loop so year sheets can be included.

        if opts.do_consensus_matrix:
            self.stdout.write("- consensus matrix (html)")
            tables.write_consensus_matrix_html(
                output_filename=os.path.join(root_target, "consensus_matrix.html"),
                seo=opts.seo,
                project_title=project_title,
            )

        if opts.do_structural_similarity:
            self.stdout.write("- structural equivalence (html + json)")
            os.makedirs(root_target, exist_ok=True)
            sim_data = community_stats._compute_structural_equivalence(graph, graph_data, measures_labels)
            if sim_data is not None:
                tables.write_structural_similarity_json(sim_data, root_target)
            tables.write_structural_similarity_html(
                output_filename=os.path.join(root_target, "structural_similarity.html"),
                seo=opts.seo,
                project_title=project_title,
            )

        if opts.do_behavioural_equivalence:
            self.stdout.write("- behavioural equivalence (html + json)")
            os.makedirs(root_target, exist_ok=True)
            beh_data = community_stats._compute_behavioural_equivalence(graph_data, measures_labels)
            if beh_data is not None:
                tables.write_behavioural_equivalence_json(beh_data, root_target)
            tables.write_behavioural_equivalence_html(
                output_filename=os.path.join(root_target, "behavioural_equivalence.html"),
                seo=opts.seo,
                project_title=project_title,
            )

        if opts.do_graph or opts.do_3dgraph or opts.do_coordination:
            self.stdout.write("- media")
            exporter.copy_channel_media(channel_qs, root_target)

        if opts.do_gexf:
            self.stdout.write("- gexf")
            os.makedirs(root_target, exist_ok=True)
            exporter.write_gexf(graph, graph_data, os.path.join(root_target, "network.gexf"))

        if opts.do_graphml:
            self.stdout.write("- graphml")
            os.makedirs(root_target, exist_ok=True)
            exporter.write_graphml(graph, graph_data, os.path.join(root_target, "network.graphml"))

        if opts.do_csv:
            self.stdout.write("- csv")
            os.makedirs(root_target, exist_ok=True)
            exporter.write_csv(graph_data, edge_list, measures_labels, strategies, root_target)

        if opts.do_vacancy:
            self.stdout.write("\nVacancy analysis")
            _vac_n = [0]

            def _vac_progress(title: str) -> None:
                if _vac_n[0] > 0:
                    self.stdout.write("done")
                _vac_n[0] += 1
                self.stdout.write(f"  [{_vac_n[0]}] {title} … ", ending="")
                self.stdout.flush()

            vac_payload = vacancy_analysis.compute_vacancy_analysis(
                selected_measures=opts.selected_vacancy_measures,
                months_before=opts.vacancy_months_before,
                months_after=opts.vacancy_months_after,
                max_candidates=opts.vacancy_max_candidates,
                progress_callback=_vac_progress,
            )
            if _vac_n[0] > 0:
                self.stdout.write("done")
            else:
                self.stdout.write("- no vacancies found")
            os.makedirs(root_target, exist_ok=True)
            exporter.write_vacancy_analysis_json(vac_payload, root_target)
            self.stdout.write("- vacancy_analysis.json")
            tables.write_vacancy_analysis_html(
                output_filename=os.path.join(root_target, "vacancy_analysis.html"),
                seo=opts.seo,
                project_title=project_title,
            )
            self.stdout.write("- vacancy_analysis.html")

        if opts.do_interest_structural:
            self.stdout.write("\nInterest structural")
            int_community = _pick_interest_community_strategy(opts.communities_strategy)
            int_authority = _pick_interest_authority_key({i.measure for i in opts.measure_instances})
            self.stdout.write(f"- basis: {int_community.lower()} communities, {int_authority} authority")

            def _int_progress(label: str) -> None:
                self.stdout.write(f"  - {label}", ending="\n")
                self.stdout.flush()

            global_window_filter = _date_window_filter(opts.start_date, opts.end_date)
            if global_window_filter:
                global_qs = Message.objects.alive().filter(**global_window_filter)
                global_score_map = scoring.score_messages_for_window(global_qs)
            else:
                global_score_map = None
            int_payload = interest_structural.compute_interest_structural(
                graph_data,
                channel_dict,
                community_strategy=int_community,
                authority_key=int_authority,
                window_days=opts.interest_window_days,
                include_mentions=opts.interest_include_mentions,
                progress=_int_progress,
                window_filter=global_window_filter or None,
                interest_score_override=global_score_map,
            )
            os.makedirs(root_target, exist_ok=True)
            exporter.write_interest_structural_json(int_payload, root_target)
            self.stdout.write("- interest_structural.json")
            tables.write_interest_structural_html(
                output_filename=os.path.join(root_target, "interest_structural.html"),
                seo=opts.seo,
                project_title=project_title,
            )
            self.stdout.write("- interest_structural.html")

        global_rob_payload: dict | None = None
        if opts.do_robustness:
            self.stdout.write("\nRobustness analysis")
            _rob_first = [True]

            def _rob_progress(label: str) -> None:
                if not _rob_first[0]:
                    self.stdout.write("done")
                _rob_first[0] = False
                self.stdout.write(f"  - {label} … ", ending="")
                self.stdout.flush()

            # Only feed partitions with more than one community — trivial partitions
            # would make every edge intra and produce a flat modular curve.
            partitions: dict = {}
            for inst in opts.communities_strategy:
                cmap = strategy_results[inst.key][0]
                if len(set(cmap.values())) > 1:
                    partitions[inst.key] = cmap
            global_rob_payload = robustness.run_robustness(
                graph,
                partitions=partitions or None,
                config=robustness.RobustnessConfig(
                    alpha=opts.robustness_alpha,
                    strategies=list(opts.robustness_strategies) if opts.robustness_strategies else None,
                    n_random_runs=opts.robustness_runs,
                    n_null=opts.robustness_null,
                    seed=opts.robustness_seed,
                    reach_sample=opts.robustness_sample,
                ),
                progress=_rob_progress,
            )
            if not _rob_first[0]:
                self.stdout.write("done")
            os.makedirs(root_target, exist_ok=True)
            exporter.write_robustness_json(global_rob_payload, root_target)
            self.stdout.write("- robustness.json")
            if opts.do_html:
                tables.write_robustness_table_html(
                    output_filename=os.path.join(root_target, "robustness_table.html"),
                    seo=opts.seo,
                    project_title=project_title,
                )
                self.stdout.write("- robustness_table.html")
            # Excel write is deferred until after the timeline loop so per-year
            # robustness payloads can be folded into the same workbook.

        coordination_written = False
        # Full-range coordination layouts double as the per-year reference (same
        # seeding/orientation-alignment scheme the main map uses for timeline years).
        coord_reference_positions: dict | None = None
        coord_reference_positions_3d: dict | None = None
        if opts.do_coordination:
            self.stdout.write("\nCoordination analysis")
            self.stdout.write(
                f"- co-forwarding pairs (window {opts.coordination_window}s, "
                f"min shared origins {opts.coordination_min_events}) … ",
                ending="",
            )
            self.stdout.flush()
            coord_result = coordination.compute_coordination(
                [int(cid) for cid in channel_dict],
                start_date=opts.start_date,
                end_date=opts.end_date,
                window_seconds=opts.coordination_window,
                min_events=opts.coordination_min_events,
            )
            self.stdout.write(f"{len(coord_result.edges)} ties among {len(coord_result.node_ids)} channels")
            if coord_result.edges:
                co_graph = coordination.build_nx_graph(coord_result, graph)
                co_iterations = layout.resolve_iterations(opts.fa2_iterations, co_graph.number_of_nodes())
                self.stdout.write(f"- layout 2D (ForceAtlas2, {co_iterations} iterations) … ", ending="")
                self.stdout.flush()
                co_positions = layout.forceatlas2_positions(
                    co_graph, layout.kamada_kawai_positions(co_graph), co_iterations
                )
                # Match the export's target orientation, mirroring the main map's heuristic.
                xs, ys = zip(*co_positions.values(), strict=False)
                co_width, co_height = max(xs) - min(xs), max(ys) - min(ys)
                if (opts.target_layout == layout.LAYOUT_HORIZONTAL and co_height > co_width) or (
                    opts.target_layout == layout.LAYOUT_VERTICAL and co_width > co_height
                ):
                    co_positions = layout.rotate_positions(co_positions)
                self.stdout.write("done")
                co_positions_3d = None
                if opts.do_coordination_3d:
                    self.stdout.write(f"- layout 3D (ForceAtlas2, {co_iterations} iterations) … ", ending="")
                    self.stdout.flush()
                    co_positions_3d = layout.forceatlas2_positions_3d(
                        co_graph, layout.kamada_kawai_positions_3d(co_graph), co_iterations
                    )
                    self.stdout.write("done")
                coord_reference_positions = co_positions
                coord_reference_positions_3d = co_positions_3d
                coord_graph_data = exporter.build_coordination_graph_data(graph_data, coord_result, co_positions)
                exporter.write_coordination_files(
                    coord_graph_data,
                    co_positions_3d,
                    coordination.coordination_measures_labels(),
                    root_target,
                    communities_data=communities_data,
                )
                self.stdout.write("- data_coordination/ files")
                exporter.write_coordination_pages(
                    root_target,
                    seo=opts.seo,
                    project_title=project_title,
                    vertical_layout=opts.vertical_layout,
                    node_count=len(coord_graph_data["nodes"]),
                    tie_count=len(coord_result.edges),
                    strategy_labels=community.labelgroup_display_labels(),
                    include_2d=opts.do_coordination_2d,
                    include_3d=opts.do_coordination_3d,
                )
                written_pages = [
                    name
                    for flag, name in (
                        (opts.do_coordination_2d, "coordination.html"),
                        (opts.do_coordination_3d, "coordination3d.html"),
                    )
                    if flag
                ]
                self.stdout.write(f"- {', '.join(written_pages)}")
                coordination_written = True
            else:
                self.stdout.write(
                    self.style.WARNING(
                        "- no coordinated pairs at these thresholds; coordination maps skipped "
                        "(widen --coordination-window or lower --coordination-min-events to loosen them)"
                    )
                )

        timeline_entries: list[dict] = []
        if opts.timeline_step == "year":
            year_range = _timeline_year_range(opts.start_date, opts.end_date)
            if year_range is None:
                self.stdout.write(self.style.WARNING("\nTimeline: no messages found, skipping."))
            else:
                first_year, last_year = year_range
                self.stdout.write(f"\nTimeline export ({first_year}–{last_year})")
                for yr in range(first_year, last_year + 1):
                    entry = self._run_year_export(
                        yr,
                        root_target,
                        options,
                        opts.measure_instances,
                        opts.communities_strategy,
                        strategies,
                        opts.do_graph,
                        opts.do_3dgraph,
                        opts.do_xlsx,
                        opts.channel_types,
                        opts.channel_sources,
                        opts.edge_weight_strategy,
                        opts.fa2_iterations,
                        opts.target_layout,
                        opts.seo,
                        project_title,
                        opts.selected_network_groups,
                        reference_positions=positions if opts.do_graph else None,
                        reference_positions_3d=positions_3d if opts.do_3dgraph else None,
                        extra_layout_names=opts.extra_layout_names or None,
                        extra_layout_names_3d=opts.extra_layout_names_3d or None,
                        do_robustness=opts.do_robustness,
                        robustness_alpha=opts.robustness_alpha,
                        robustness_strategies=opts.robustness_strategies,
                        robustness_runs=opts.robustness_runs,
                        robustness_null=opts.robustness_null,
                        robustness_seed=opts.robustness_seed,
                        robustness_sample=opts.robustness_sample,
                        do_interest_structural=opts.do_interest_structural,
                        interest_window_days=opts.interest_window_days,
                        interest_include_mentions=opts.interest_include_mentions,
                        # Only when the full range produced ties: a year's ties are a
                        # subset of the full range's, so an empty full range means
                        # every per-year run would come back empty too.
                        do_coordination=opts.do_coordination and coordination_written,
                        do_coordination_3d=opts.do_coordination_3d,
                        coordination_window=opts.coordination_window,
                        coordination_min_events=opts.coordination_min_events,
                        coord_reference_positions=coord_reference_positions,
                        coord_reference_positions_3d=coord_reference_positions_3d,
                        window_start=opts.start_date,
                        window_end=opts.end_date,
                        temporal_results=temporal_results,
                    )
                    if entry is not None:
                        timeline_entries.append(entry)
                if timeline_entries:
                    tables.write_timeline_json(timeline_entries, graph_dir=root_target)
                    if coordination_written and any(e.get("has_coordination") for e in timeline_entries):
                        exporter.write_coordination_timeline_json(timeline_entries, root_target)

        if opts.do_xlsx:
            year_xlsx = [
                (e["year"], e["_xlsx_graph_data"], e["_xlsx_community_data"])
                for e in timeline_entries
                if e.get("_xlsx_graph_data") is not None
            ]
            channel_years = [(yr, gd) for yr, gd, _ in year_xlsx] or None
            network_years = [(yr, ctd) for yr, _, ctd in year_xlsx if ctd is not None] or None
            self.stdout.write("- table (xlsx)")
            tables.write_table_xlsx(
                graph_data,
                measures_labels,
                strategies,
                output_filename=os.path.join(root_target, "channel_table.xlsx"),
                project_title=project_title,
                year_data=channel_years,
            )
            self.stdout.write("- network table (xlsx)")
            tables.write_network_table_xlsx(
                community_table_data,
                strategies,
                output_filename=os.path.join(root_target, "network_table.xlsx"),
                project_title=project_title,
                year_data=network_years,
            )
            self.stdout.write("- community table (xlsx)")
            tables.write_community_table_xlsx(
                community_table_data,
                strategies,
                output_filename=os.path.join(root_target, "community_table.xlsx"),
                project_title=project_title,
                year_data=network_years,
            )
            if opts.do_robustness and global_rob_payload is not None:
                robustness_years = [
                    (e["year"], e["_xlsx_robustness_data"])
                    for e in timeline_entries
                    if e.get("_xlsx_robustness_data") is not None
                ] or None
                self.stdout.write("- robustness table (xlsx)")
                tables.write_robustness_table_xlsx(
                    global_rob_payload,
                    output_filename=os.path.join(root_target, "robustness_table.xlsx"),
                    project_title=project_title,
                    year_data=robustness_years,
                )

        self.stdout.write("- index")
        os.makedirs(root_target, exist_ok=True)
        tables.write_index_html(
            output_filename=os.path.join(root_target, "index.html"),
            seo=opts.seo,
            project_title=project_title,
            include_graph=opts.do_graph,
            include_3d_graph=opts.do_3dgraph,
            include_channel_html=opts.do_html,
            include_channel_xlsx=opts.do_xlsx,
            include_network_html=opts.do_html,
            include_network_xlsx=opts.do_xlsx,
            include_community_html=opts.do_html,
            include_community_xlsx=opts.do_xlsx,
            include_compare_html=False,
            compare_files=set(),
            strategies=strategies,
            include_consensus_matrix_html=opts.do_consensus_matrix,
            include_structural_similarity=opts.do_structural_similarity,
            include_behavioural_equivalence=opts.do_behavioural_equivalence,
            timeline_entries=timeline_entries or None,
            include_vacancy_analysis=opts.do_vacancy,
            include_robustness_html=opts.do_robustness and opts.do_html,
            include_robustness_xlsx=opts.do_robustness and opts.do_xlsx,
            include_interest_structural=opts.do_interest_structural,
            include_coordination_2d=coordination_written and opts.do_coordination_2d,
            include_coordination_3d=coordination_written and opts.do_coordination_3d,
        )

        exporter.write_summary_json(root_target, opts.export_name or None, options, len(graph.nodes), len(graph.edges))

        _atomic_publish(root_target, _final_target)
        self.stdout.write(self.style.SUCCESS("\nDone."))
