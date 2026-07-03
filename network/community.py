import re
from collections import Counter
from collections.abc import Iterable
from itertools import combinations
from typing import Any

from django.utils.text import slugify

from network.tokens import TokenInstance, TokenParam, TokenSpec, base_keys_for, canonical_key, parse_tokens
from network.utils import to_undirected_sum
from webapp.models import Label, LabelGroup
from webapp.utils.colors import (
    DEFAULT_FALLBACK_COLOR,
    ColorTuple,
    expand_colors,
    palette_colors,
    parse_color,
    rgb_avg,
    rgb_to_hex,
)

import igraph as ig
import leidenalg
import networkx as nx

# Canonical ordered list of community-strategy names. Mirrors measures.ALL_STRATEGIES (which feeds
# the measure "basis" choices); a guard test keeps the two in sync. LEIDEN_CPM is a single
# parameterised strategy (its resolution γ is per-instance and it may be requested more than once),
# replacing the old fixed LEIDEN_CPM_COARSE / LEIDEN_CPM_FINE presets. CONSENSUS is derived from
# the other selected strategies' partitions (dispatched after them; see detect_consensus).
# LABELPROPAGATION was removed in v0.27 (unweighted *and* undirected, so it discarded both the
# edge-weight and the direction signal; its cheap-baseline role is superseded by CONSENSUS).
ALL_STRATEGIES: list[str] = [
    "LEIDEN",
    "LEIDEN_DIRECTED",
    "LEIDEN_CPM",
    "LEIDEN_TEMPORAL",
    "LOUVAIN",
    "KCORE",
    "SBM",
    "SBM_ASSORTATIVE",
    "CONSENSUS",
]

# Strategies the ``ALL`` token does NOT expand to. LEIDEN_TEMPORAL hard-requires a year timeline
# (``--timeline-step year``), so folding it into ALL would break every non-timeline ``ALL`` run;
# it must be requested explicitly.
EXCLUDED_FROM_ALL: frozenset[str] = frozenset({"LEIDEN_TEMPORAL"})
# Every static strategy is an algorithm; the only *metadata* partitions are the dynamic, DB-keyed
# ``LABELGROUP<id>`` strategies (one per partition LabelGroup), which replaced the old single
# ``ORGANIZATION`` strategy. ``is_metadata_strategy`` distinguishes them.
COMMUNITY_ALGORITHMS: frozenset[str] = frozenset(ALL_STRATEGIES)
VALID_STRATEGIES: frozenset[str] = frozenset(ALL_STRATEGIES)

_LABELGROUP_RE = re.compile(r"^LABELGROUP(\d+)$")


def labelgroup_id(strategy_name: str) -> int | None:
    """The LabelGroup pk a ``LABELGROUP<id>`` strategy token selects, or ``None`` for algorithms."""
    match = _LABELGROUP_RE.match(strategy_name.upper())
    return int(match.group(1)) if match else None


def is_metadata_strategy(strategy_name: str) -> bool:
    """Whether a strategy is a manual ``LABELGROUP<id>`` partition rather than an algorithm."""
    return labelgroup_id(strategy_name) is not None


def labelgroup_strategy_tokens() -> list[str]:
    """``LABELGROUP<id>`` tokens for every partition LabelGroup, in pk order (DB lookup)."""
    return [f"LABELGROUP{pk}" for pk in LabelGroup.objects.filter(is_partition=True).values_list("pk", flat=True)]


def labelgroup_display_labels() -> dict[str, str]:
    """Map each partition LabelGroup's lowercase ``labelgroup<id>`` partition key to its display name.

    Injected into the static viewer as ``window.STRATEGY_LABELS`` so a label-group colour-by option
    shows the analyst's group name (e.g. "Region") rather than the title-cased key ("Labelgroup3").
    The key matches ``StrategyInstance.key`` for a ``LABELGROUP<id>`` token (``name.lower()``).
    """
    return {
        f"labelgroup{pk}": name for pk, name in LabelGroup.objects.filter(is_partition=True).values_list("pk", "name")
    }


# Tag appended to a label group's name wherever it is offered as a community/strategy *option* outside
# its own picker — the MODULEROLE basis select, the table / CSV / GEXF export columns, and the viewer's
# colour-by selector (mirrored by ``strategy_label`` in webapp_engine/map/js/labels.js). Inside the
# Operations "Label groups" fieldset the bare name is shown, since the context is already unambiguous.
CUSTOM_LABEL_SUFFIX = " [custom label]"


def custom_label_display(name: str) -> str:
    """A label-group name tagged as a manual ("custom") partition, for display outside its own picker."""
    return f"{name}{CUSTOM_LABEL_SUFFIX}"


# Strategies whose partition is optimised (or computed) on the UNDIRECTED projection
# of the citation graph. Their reported modularity should use the undirected null
# model (k_i·k_j / 2m), matching what they actually optimised — not the directed
# null model (k_out_i·k_in_j / m). Keys are the lowercased community keys.
# Everything else (leiden_directed, organization) is reported with directed
# modularity, the form it was built against.
# Keys are *canonical* (parameter-suffix-stripped) strategy keys — membership is tested via
# canonical_strategy_key(), so every LEIDEN_CPM instance (whatever its resolution) is covered.
# CONSENSUS is optimised on the (undirected) co-assignment graph, not the citation graph;
# its modularity is reported against the undirected projection, the closest null. LEIDEN_TEMPORAL
# and SBM_ASSORTATIVE are both fitted on the undirected W+Wᵀ projection (per-year slices for the
# former), so they report against the undirected null too.
UNDIRECTED_BASIS_STRATEGIES: frozenset[str] = frozenset(
    {"leiden", "leiden_cpm", "leiden_temporal", "louvain", "kcore", "sbm_assortative", "consensus"}
)

# Human-readable labels for the strategy keys above — mirrors STRATEGY_LABELS in
# webapp_engine/map/js/labels.js so the same display text shows up in browser
# pages and in the server-side Operations panel.
COMMUNITY_STRATEGY_LABELS: dict[str, str] = {
    "LEIDEN": "Leiden",
    "LEIDEN_DIRECTED": "Leiden directed",
    "LEIDEN_CPM": "Leiden CPM",
    "LEIDEN_TEMPORAL": "Leiden temporal",
    "LOUVAIN": "Louvain",
    "KCORE": "K-core",
    "SBM": "Stochastic block model",
    "SBM_ASSORTATIVE": "Assortative SBM",
    "CONSENSUS": "Consensus",
}


def consensus_eligible(strategy_name: str) -> bool:
    """Whether a strategy's partition may feed consensus aggregation (the CONSENSUS strategy
    and the consensus-matrix balloon plot alike).

    Eligible = a genuine algorithmic community detection *of the graph under analysis*: not a
    manual ``LABELGROUP<id>`` partition, not the KCORE shell decomposition (a connectivity
    hierarchy, not a community detection), not CONSENSUS itself (a derived partition must not
    feed its own input — nor double-count in the matrix it summarises), and not LEIDEN_TEMPORAL
    (its full-range column is a plurality summary across timeline slices and its per-year
    partitions are deliberately coupled to neighbouring years — neither is an independent
    detection of the graph being aggregated). Mirrored by ``_consensusExcluded`` in
    webapp_engine/map/js/consensus_matrix.js.
    """
    name = strategy_name.upper()
    return name not in {"KCORE", "CONSENSUS", "LEIDEN_TEMPORAL"} and not is_metadata_strategy(name)


# ── Parameterised community strategies & strategy instances ────────────────────
#
# Most strategies are parameter-free, but LEIDEN_CPM takes a tunable knob and may be requested more
# than once with different settings — e.g. LEIDEN_CPM(resolution=0.01) alongside
# LEIDEN_CPM(resolution=0.05). The shared token machinery (network.tokens) turns the comma-separated
# --community-strategies value into an ordered list of StrategyInstance objects; each instance maps to
# a distinct, parameter-suffixed partition key (``StrategyInstance.key``) so two instances of one
# strategy never overwrite each other's communities[...] entry. This mirrors the measures system.

StrategyParam = TokenParam
StrategySpec = TokenSpec

CPM_DEFAULT_RESOLUTION = 0.05
SBM_DEFAULT_MODE = "NESTED"
CONSENSUS_DEFAULT_THRESHOLD = 0.5
# leidenalg's own default coupling weight; higher ω = smoother, more persistent communities
# across years, lower ω = each year re-partitioned nearly independently.
TEMPORAL_DEFAULT_INTERSLICE = 1.0

# Base key of the per-channel SBM assignment-confidence companion column written by
# SBM(refine=MCMC); the per-instance parameter suffix is appended at compute time
# (sbm_mode_nested_refine_mcmc → sbm_confidence_mode_nested_refine_mcmc).
SBM_CONFIDENCE_BASE_KEY = "sbm_confidence"

PARAMETERISED_STRATEGIES: dict[str, StrategySpec] = {
    "LEIDEN_CPM": StrategySpec(
        "LEIDEN_CPM",
        "Leiden CPM",
        params=(
            StrategyParam(
                "resolution",
                "float",
                CPM_DEFAULT_RESOLUTION,
                minimum=0.0,
                label="Resolution γ",
                help="CPM resolution: a community is stable when its internal edge density exceeds γ. "
                "Lower = fewer, larger communities (γ ≈ 0.01); higher = more, "
                "smaller communities (γ ≈ 0.05).",
            ),
        ),
        primary_keys=("leiden_cpm",),
    ),
    "SBM": StrategySpec(
        "SBM",
        "Stochastic block model",
        params=(
            StrategyParam(
                "mode",
                "enum",
                SBM_DEFAULT_MODE,
                choices=("FLAT", "NESTED"),
                label="Mode",
                help="NESTED = nested SBM (Peixoto 2017), partition taken at the finest level — better "
                "model selection on large graphs. FLAT = single-level SBM. May be added once per mode.",
            ),
            StrategyParam(
                "weights",
                "enum",
                "",
                choices=("POISSON", "EXPONENTIAL"),
                label="Weights",
                help="Edge-covariate model for a weighted SBM fit (Peixoto 2018). Empty = binary fit on the "
                "bare citation structure (the historical behaviour, invariant to --edge-weight-strategy). "
                "POISSON models weights as discrete counts — pair with --edge-weight-strategy TOTAL; "
                "EXPONENTIAL models them as positive reals — pair with the ratio-valued PARTIAL_* strategies.",
            ),
            StrategyParam(
                "refine",
                "enum",
                "",
                choices=("MCMC",),
                label="Refine",
                help="Empty = single minimum-description-length fit. MCMC equilibrates the fit and samples "
                "the posterior (Peixoto 2014; 2021), reporting each channel's most probable block plus a "
                "per-channel assignment-confidence column (share of posterior samples agreeing).",
            ),
        ),
        primary_keys=("sbm",),
        aux_keys=(SBM_CONFIDENCE_BASE_KEY,),
    ),
    "LEIDEN_TEMPORAL": StrategySpec(
        "LEIDEN_TEMPORAL",
        "Leiden temporal",
        params=(
            StrategyParam(
                "resolution",
                "float",
                CPM_DEFAULT_RESOLUTION,
                minimum=0.0,
                label="Resolution γ",
                help="CPM resolution of each year slice, as in LEIDEN_CPM: lower = fewer, larger "
                "communities; higher = more, smaller ones.",
            ),
            StrategyParam(
                "interslice",
                "float",
                TEMPORAL_DEFAULT_INTERSLICE,
                minimum=0.0,
                label="Coupling ω",
                help="Weight of the identity link tying each channel to itself in adjacent years "
                "(Mucha et al. 2010). 0 = years partitioned independently; higher = smoother, more "
                "persistent communities across the timeline.",
            ),
        ),
        primary_keys=("leiden_temporal",),
    ),
    "SBM_ASSORTATIVE": StrategySpec(
        "SBM_ASSORTATIVE",
        "Assortative SBM",
        params=(
            StrategyParam(
                "refine",
                "enum",
                "",
                choices=("MCMC",),
                label="Refine",
                help="Empty = single greedy fit. MCMC equilibrates the fit and samples the posterior, "
                "reporting each channel's most probable community plus a per-channel "
                "assignment-confidence column (share of posterior samples agreeing).",
            ),
        ),
        primary_keys=("sbm_assortative",),
    ),
    "CONSENSUS": StrategySpec(
        "CONSENSUS",
        "Consensus",
        params=(
            StrategyParam(
                "threshold",
                "float",
                CONSENSUS_DEFAULT_THRESHOLD,
                minimum=0.0,
                maximum=1.0,
                label="Threshold τ",
                help="Minimum share of the input partitions that must co-assign two channels for the "
                "pair to survive into the consensus graph (Lancichinetti & Fortunato 2012). "
                "0.5 = a majority of the algorithms agree; higher = stricter, smaller cores.",
            ),
        ),
        primary_keys=("consensus",),
    ),
}

# Base partition keys owned by a parameterised strategy, longest first — feeds canonical_strategy_key.
_STRATEGY_BASE_KEYS: tuple[str, ...] = base_keys_for(PARAMETERISED_STRATEGIES)


class StrategyInstance(TokenInstance):
    """One requested community strategy with its resolved parameters.

    Thin :class:`~network.tokens.TokenInstance` subclass exposing ``strategy`` (the name), its
    ``spec`` from ``PARAMETERISED_STRATEGIES``, and ``key`` — the parameter-suffixed node-attribute
    key under which this instance's partition lives in ``node['communities']`` (e.g.
    ``leiden_cpm_resolution_0_05``; just ``leiden_directed`` for parameter-free strategies, identical
    to the legacy lowercase name).
    """

    @property
    def strategy(self) -> str:
        return self.name

    @property
    def spec(self) -> "StrategySpec | None":
        return PARAMETERISED_STRATEGIES.get(self.name)

    @property
    def key(self) -> str:
        return self.name.lower() + self.suffix()

    @property
    def label(self) -> str:
        gid = labelgroup_id(self.name)
        if gid is not None:
            group = LabelGroup.objects.filter(pk=gid).first()
            base = custom_label_display(group.name) if group else self.name
        else:
            base = COMMUNITY_STRATEGY_LABELS.get(self.name, self.name.title())
        return base + self.label_annotation()


def parse_strategies(
    tokens: list[str],
    *,
    defaults: dict[str, dict[str, object]] | None = None,
) -> list["StrategyInstance"]:
    """Parse ``--community-strategies`` tokens into ordered, de-duplicated StrategyInstance objects.

    ``ALL`` expands to every strategy with default parameters — including one ``LABELGROUP<id>`` per
    partition LabelGroup (queried fresh each call, so newly-added groups appear). ``defaults`` supplies
    per-strategy parameter overrides for omitted values (the command passes the global
    ``--leiden-cpm-resolution`` so a bare ``LEIDEN_CPM`` inherits it). Raises ``ValueError`` on unknown
    strategies, bad/duplicate parameters — mirroring ``measures.parse_measures``.
    """
    labelgroup_tokens = labelgroup_strategy_tokens()
    return parse_tokens(
        tokens,
        registry=PARAMETERISED_STRATEGIES,
        known_tokens=VALID_STRATEGIES | set(labelgroup_tokens),
        # ALL expands to the metadata partitions first (the old ORGANIZATION-first order), then the
        # algorithms — minus the strategies that only work in specific run shapes (EXCLUDED_FROM_ALL:
        # LEIDEN_TEMPORAL needs a year timeline, so it must be requested explicitly).
        all_tokens=labelgroup_tokens + [s for s in ALL_STRATEGIES if s not in EXCLUDED_FROM_ALL],
        instance_cls=StrategyInstance,
        defaults=defaults,
        noun="strategy",
    )


def canonical_strategy_key(key: str) -> str:
    """Strip a parameter suffix back to the base strategy key (``leiden_cpm_resolution_0_05`` →
    ``leiden_cpm``). Parameter-free keys are returned unchanged."""
    return canonical_key(key, _STRATEGY_BASE_KEYS)


def strategy_display_label(key: str) -> str:
    """Human label for a partition key, e.g. ``leiden_cpm_resolution_0_05`` → ``Leiden CPM (resolution=0.05)``.

    Mirrors ``StrategyInstance.label`` but works from the bare node-attribute key (used by the static
    table/CSV writers, which only have the key). The base maps through ``COMMUNITY_STRATEGY_LABELS``; the
    parameter suffix is reconstructed from the spec's param names (the float value slug ``0_05`` reads
    back as ``0.05``). The JS mirror is ``strategy_label`` in ``webapp_engine/map/js/labels.js``.
    """
    gid = labelgroup_id(key)
    if gid is not None:
        group = LabelGroup.objects.filter(pk=gid).first()
        return custom_label_display(group.name) if group else key
    base = canonical_strategy_key(key)
    label = COMMUNITY_STRATEGY_LABELS.get(base.upper(), base.replace("_", " ").title())
    if key == base:
        return label
    spec = PARAMETERISED_STRATEGIES.get(base.upper())
    rest = key[len(base) + 1 :]  # drop "base_" → e.g. "mode_nested_weights_poisson"
    parts: list[str] = []
    params = list(spec.params) if spec else []
    for i, param in enumerate(params):
        prefix = f"{param.name}_"
        if not rest.startswith(prefix):
            continue  # omitted (empty-default) parameter — absent from the suffix
        value_part = rest[len(prefix) :]
        # The value runs until the next declared parameter's "_<name>_" boundary (suffix order is
        # spec order, so only later params can follow). Enum values carry no "_" and float slugs
        # are digits and "_", so a parameter-name boundary is unambiguous.
        cut = len(value_part)
        for later in params[i + 1 :]:
            pos = value_part.find(f"_{later.name}_")
            if pos != -1 and pos < cut:
                cut = pos
        raw = value_part[:cut]
        rest = value_part[cut + 1 :] if cut < len(value_part) else ""
        value = raw.replace("_", ".") if param.kind == "float" else raw
        parts.append(f"{param.name}={value}")
    return f"{label} ({', '.join(parts)})" if parts else label


def sbm_confidence_key(strategy_key: str) -> str:
    """Node-attribute key of the SBM assignment-confidence column for an SBM-family instance key.

    ``sbm_mode_nested_refine_mcmc`` → ``sbm_confidence_mode_nested_refine_mcmc``;
    ``sbm_assortative_refine_mcmc`` → ``sbm_confidence_assortative_refine_mcmc``. Only populated
    when the instance ran with ``refine=MCMC``; exporters probe the nodes for its presence.
    """
    return SBM_CONFIDENCE_BASE_KEY + strategy_key[len("sbm") :]


def sbm_confidence_display_label(strategy_key: str) -> str:
    """Human label for an SBM-family confidence column, e.g. ``SBM confidence (mode=nested, refine=mcmc)``
    or ``Assortative SBM confidence (refine=mcmc)``."""
    prefix = (
        "Assortative SBM confidence" if canonical_strategy_key(strategy_key) == "sbm_assortative" else "SBM confidence"
    )
    label = strategy_display_label(strategy_key)
    idx = label.find(" (")
    return prefix + (label[idx:] if idx != -1 else "")


type CommunityMap = dict[str, int]
type CommunityPalette = dict[int, ColorTuple]


def build_community_label(community_id: int | str, strategy: str) -> str:
    return slugify(f"{community_id}-{strategy}")


def normalize_community_map(community_map: CommunityMap) -> CommunityMap:
    community_counts = Counter(community_map.values())
    ordered = sorted(community_counts.items(), key=lambda item: (-item[1], item[0]))
    remap = {community_id: index for index, (community_id, _) in enumerate(ordered, start=1)}
    return {node_id: remap[community_id] for node_id, community_id in community_map.items()}


def build_community_palette(
    community_map: CommunityMap,
    palette_name: str,
    *,
    reverse: bool = False,
) -> CommunityPalette:
    if not community_map:
        return {}
    total = max(community_map.values())
    source_colors = palette_colors(palette_name, reverse=reverse)
    colors = expand_colors(source_colors, total)
    return {
        index: parse_color(colors[index - 1]) if index <= len(colors) else DEFAULT_FALLBACK_COLOR
        for index in range(1, total + 1)
    }


def _merge_isolated_nodes(graph: nx.DiGraph, community_map: CommunityMap) -> CommunityMap:
    """Assign all isolated nodes (no edges) to the same community as the first isolated node."""
    isolated = sorted((node_id for node_id in graph.nodes() if graph.degree(node_id) == 0), key=str)
    if len(isolated) <= 1:
        return community_map
    target_community = community_map[isolated[0]]
    for node_id in isolated[1:]:
        community_map[node_id] = target_community
    return community_map


# ── Shared scaffolding for the per-algorithm detect_* functions ────────────────


def _node_id_index(graph: nx.DiGraph) -> tuple[list[str], dict[str, int]]:
    """Stable sorted ``node_ids`` plus ``{node_id: index}`` map. Used by every
    igraph- or matrix-based detector to translate between str ids and 0..n-1 indices."""
    node_ids = sorted(graph.nodes())
    return node_ids, {node_id: index for index, node_id in enumerate(node_ids)}


def _build_directed_igraph(
    graph: nx.DiGraph, node_ids: list[str], node_id_map: dict[str, int]
) -> tuple[ig.Graph, list[float]]:
    """Build a directed igraph from a NetworkX DiGraph preserving edge weights."""
    ig_graph = ig.Graph(n=len(node_ids), directed=True)
    edges = [(node_id_map[s], node_id_map[t]) for s, t in graph.edges()]
    weights = [graph.edges[s, t].get("weight", 1.0) for s, t in graph.edges()]
    ig_graph.add_edges(edges)
    return ig_graph, weights


def _assign_from_partition(partition: Iterable, node_ids: list[str]) -> CommunityMap:
    """Build {node_id: community_index} from an iterable of communities-as-node-indices."""
    community_map: CommunityMap = {}
    for community_index, community in enumerate(partition, start=1):
        for node_index in community:
            community_map[node_ids[node_index]] = community_index
    return community_map


def _assign_from_node_sets(communities: Iterable[Iterable[str]]) -> CommunityMap:
    """Build {node_id: community_index} from an iterable of communities-as-node-id-sets."""
    community_map: CommunityMap = {}
    for index, community in enumerate(communities, start=1):
        for node_id in community:
            community_map[node_id] = index
    return community_map


def _finalize_partition(
    graph: nx.DiGraph,
    community_map: CommunityMap,
    palette_name: str,
    *,
    reverse: bool = False,
    merge_isolated: bool = True,
) -> tuple[CommunityMap, CommunityPalette]:
    """Common closing for every detect_* function: optional isolated-node merge,
    canonical id renumbering, palette construction."""
    if merge_isolated:
        community_map = _merge_isolated_nodes(graph, community_map)
    community_map = normalize_community_map(community_map)
    return community_map, build_community_palette(community_map, palette_name, reverse=reverse)


# ── Detection algorithms ──────────────────────────────────────────────────────


def detect_labelgroup(group_id: int, channel_dict: dict[str, Any]) -> tuple[CommunityMap, CommunityPalette]:
    """Partition nodes by their resolved label in LabelGroup ``group_id`` for the window.

    Reads the per-group window resolution ``graph_builder`` stored in ``node['group_partitions']``;
    nodes with no label in the group (dead leaves, or simply unlabelled in this group) are left
    ungrouped. The primary group resolves in-target labels only; a descriptive group (e.g. "Nation")
    partitions by every label it carries, in-target or not. Community ids are ``Label`` pks and the
    palette is built from each label's own colour, so the ``palette_name`` / ``reverse`` flags don't
    apply (as the old ORGANIZATION strategy).
    """
    community_map: CommunityMap = {}
    community_palette: CommunityPalette = {}
    for channel_id, item in channel_dict.items():
        entry = (item["data"].get("group_partitions") or {}).get(group_id)
        if entry is None:
            continue
        label_id, label_color = entry
        community_map[channel_id] = label_id
        if label_id not in community_palette:
            community_palette[label_id] = parse_color(label_color)
    return community_map, community_palette


def detect_kcore(
    graph: nx.DiGraph, palette_name: str, *, reverse: bool = False
) -> tuple[CommunityMap, CommunityPalette]:
    """K-core decomposition (Seidman 1983; Kitsak et al. 2010).

    A node's coreness is the largest k such that it belongs to the maximal subgraph
    where every member has at least k internal connections. Communities are the
    resulting k-shells, numbered from the innermost (community 1) outwards — the
    shell order IS the information, so we bypass ``_finalize_partition`` rather
    than renumbering by community size like every other detector.

    Computed on the W+Wᵀ undirected projection (``to_undirected_sum``) with self-loops
    removed (``nx.core_number`` rejects them, and they're present whenever
    ``--self-references`` is on). ``nx.core_number`` is unweighted, so the partition
    is invariant to ``--edge-weight-strategy``. Isolated nodes (coreness 0) are
    folded into shell 1 and end up in the outermost community.
    """
    undirected = to_undirected_sum(graph)
    undirected.remove_edges_from(nx.selfloop_edges(undirected))
    coreness = nx.core_number(undirected)
    raw: CommunityMap = {node_id: max(k, 1) for node_id, k in coreness.items()}
    shells = sorted(set(raw.values()), reverse=True)
    remap = {shell: index for index, shell in enumerate(shells, start=1)}
    community_map: CommunityMap = {node_id: remap[shell] for node_id, shell in raw.items()}
    return community_map, build_community_palette(community_map, palette_name, reverse=reverse)


def detect_leiden(
    graph: nx.DiGraph, palette_name: str, *, reverse: bool = False
) -> tuple[CommunityMap, CommunityPalette]:
    node_ids, node_id_map = _node_id_index(graph)
    ig_graph, weights = _build_undirected_igraph(graph, node_ids, node_id_map)
    if weights:
        ig_graph.es["weight"] = weights
    partition = leidenalg.find_partition(
        ig_graph,
        leidenalg.ModularityVertexPartition,
        weights="weight" if weights else None,
        seed=0,
    )
    return _finalize_partition(graph, _assign_from_partition(partition, node_ids), palette_name, reverse=reverse)


def detect_leiden_directed(
    graph: nx.DiGraph, palette_name: str, *, reverse: bool = False
) -> tuple[CommunityMap, CommunityPalette]:
    """Directed modularity (Leicht & Newman 2008) via leidenalg.

    Uses ModularityVertexPartition on a directed igraph so the null model is
    k_out_i * k_in_j / m rather than the undirected k_i * k_j / (2m).
    Communities are built from asymmetric citation patterns: a source that
    cites many channels without being cited back is treated differently from
    a target that is widely cited.  Edge direction is preserved throughout
    the optimisation.
    """
    node_ids, node_id_map = _node_id_index(graph)
    ig_graph, weights = _build_directed_igraph(graph, node_ids, node_id_map)
    if weights:
        ig_graph.es["weight"] = weights
    partition = leidenalg.find_partition(
        ig_graph,
        leidenalg.ModularityVertexPartition,
        weights="weight" if weights else None,
        seed=0,
    )
    return _finalize_partition(graph, _assign_from_partition(partition, node_ids), palette_name, reverse=reverse)


def _build_undirected_igraph(
    graph: nx.DiGraph, node_ids: list[str], node_id_map: dict[str, int]
) -> tuple[ig.Graph, list[float]]:
    """Build an undirected igraph from a NetworkX DiGraph, summing reciprocal edge weights."""
    undirected = to_undirected_sum(graph)
    ig_graph = ig.Graph(n=len(node_ids), directed=False)
    edges, weights = [], []
    for s, t in undirected.edges():
        edges.append((node_id_map[s], node_id_map[t]))
        weights.append(undirected.edges[s, t].get("weight", 1.0))
    ig_graph.add_edges(edges)
    return ig_graph, weights


def detect_leiden_cpm(
    graph: nx.DiGraph, palette_name: str, resolution: float, *, reverse: bool = False
) -> tuple[CommunityMap, CommunityPalette]:
    """Leiden algorithm with the Constant Potts Model objective (Traag, Van Dooren & Nesterov 2011).

    Unlike modularity, CPM has no resolution limit: a community is stable when
    its internal edge density exceeds ``resolution`` (γ), independently of
    community size.  Low γ → few large communities; high γ → many small ones.

    Same Leiden machinery as ``detect_leiden``: undirected W+Wᵀ projection via
    ``to_undirected_sum``, weights honoured, seed=0, connectivity refinement.
    Only the quality function differs.
    """
    node_ids, node_id_map = _node_id_index(graph)
    ig_graph, weights = _build_undirected_igraph(graph, node_ids, node_id_map)
    partition = leidenalg.find_partition(
        ig_graph,
        leidenalg.CPMVertexPartition,
        weights=weights if weights else None,
        resolution_parameter=resolution,
        seed=0,
    )
    return _finalize_partition(graph, _assign_from_partition(partition, node_ids), palette_name, reverse=reverse)


def detect_leiden_temporal(
    year_graphs: dict[int, nx.DiGraph],
    palette_name: str,
    resolution: float,
    interslice_weight: float,
    *,
    reverse: bool = False,
) -> tuple[dict[int, CommunityMap], CommunityMap, CommunityPalette]:
    """Interslice-coupled temporal communities over the timeline years (Mucha et al. 2010).

    ``year_graphs`` maps each non-empty timeline year to its citation graph (built with the same
    scope/weight settings as that year's export). Each year becomes one **slice** — the undirected
    W+Wᵀ projection with edge weights, exactly as ``LEIDEN_CPM`` sees a single graph — and every
    channel present in two consecutive slices is tied to *itself* across them with weight
    ``interslice_weight`` (ω). ``leidenalg.find_partition_temporal`` then optimises the CPM
    objective (``resolution`` γ, seed=0) over all slices at once, so a community's identity is
    **shared across years**: persistence, splits, and merges become properties of the partition
    itself rather than post-hoc ribbon-reading in the alluvial diagram. The identity link ties a
    channel only to itself in adjacent years — no multi-hop flow claim — so the strategy stays
    inside the one-degree attribution model.

    Returns ``(per_year, plurality, palette)``:

    * ``per_year`` — one :type:`CommunityMap` per year, all sharing a single global community-id
      space (ids renumbered once, by total membership across every slice, so "community 3" means
      the same cohort in 2021 and 2022 — and keeps the same colour).
    * ``plurality`` — the full-range summary column: each channel's most frequent community
      across the slices it appears in, ties broken by its latest year's assignment. This is a
      *derived summary* for the full-range map/table, not an independent detection of the
      full-range graph (which is why the strategy is not consensus-eligible).
    * ``palette`` — one palette over the global id space, shared by every year.

    Isolated-in-a-year channels are deliberately *not* merged into a residual community (unlike
    the single-graph detectors): the interslice coupling lets a channel isolated in one year
    inherit its neighbouring years' community, which is exactly the point of the method.
    """
    if len(year_graphs) < 2:
        raise ValueError(
            "LEIDEN_TEMPORAL needs at least two non-empty timeline years to couple; "
            f"got {len(year_graphs)}. Check --timeline-step year and the date window."
        )
    years = sorted(year_graphs)
    slices: list[ig.Graph] = []
    for year in years:
        undirected = to_undirected_sum(year_graphs[year])
        node_ids = sorted(undirected.nodes())
        node_id_map = {node_id: index for index, node_id in enumerate(node_ids)}
        slice_graph = ig.Graph(n=len(node_ids), directed=False)
        slice_graph.vs["id"] = node_ids  # identity attribute the interslice coupling joins on
        edges, weights = [], []
        for s, t in undirected.edges():
            edges.append((node_id_map[s], node_id_map[t]))
            weights.append(undirected.edges[s, t].get("weight", 1.0))
        slice_graph.add_edges(edges)
        slice_graph.es["weight"] = weights
        slices.append(slice_graph)

    memberships, _improvement = leidenalg.find_partition_temporal(
        slices,
        leidenalg.CPMVertexPartition,
        interslice_weight=interslice_weight,
        vertex_id_attr="id",
        weight_attr="weight",
        seed=0,
        resolution_parameter=resolution,
    )

    per_year: dict[int, CommunityMap] = {}
    for year, slice_graph, membership in zip(years, slices, memberships, strict=True):
        per_year[year] = {slice_graph.vs[index]["id"]: int(cid) for index, cid in enumerate(membership)}

    # One global renumbering by total membership across all slices (size desc, id asc — the
    # normalize_community_map convention, applied once so ids and colours are stable across years).
    counts = Counter(cid for community_map in per_year.values() for cid in community_map.values())
    ordered = sorted(counts.items(), key=lambda item: (-item[1], item[0]))
    remap = {cid: index for index, (cid, _) in enumerate(ordered, start=1)}
    per_year = {
        year: {node_id: remap[cid] for node_id, cid in community_map.items()}
        for year, community_map in per_year.items()
    }

    # Full-range plurality: most frequent community per channel, ties → the latest year's assignment.
    votes: dict[str, Counter] = {}
    latest: dict[str, int] = {}
    for year in years:
        for node_id, cid in per_year[year].items():
            votes.setdefault(node_id, Counter())[cid] += 1
            latest[node_id] = cid
    plurality: CommunityMap = {}
    for node_id, counter in votes.items():
        top = max(counter.values())
        tied = {cid for cid, count in counter.items() if count == top}
        plurality[node_id] = latest[node_id] if latest[node_id] in tied else min(tied)

    palette = build_community_palette({str(cid): cid for cid in remap.values()}, palette_name, reverse=reverse)
    return per_year, plurality, palette


def detect_louvain(
    graph: nx.DiGraph, palette_name: str, *, reverse: bool = False
) -> tuple[CommunityMap, CommunityPalette]:
    """Louvain modularity maximisation (Blondel et al. 2008) — the classic baseline, superseded by Leiden.

    Greedy modularity optimisation on the undirected W+Wᵀ projection
    (``to_undirected_sum``) — the same symmetrised graph and edge-weight handling
    as ``detect_leiden``; only the optimiser differs (no Leiden refinement pass).
    Louvain is the field-standard community detector that predates Leiden; it is
    kept in Pulpit so a run can be compared against the large body of older
    studies that report Louvain partitions. **For Pulpit's own analyses prefer**
    ``LEIDEN`` — or ``LEIDEN_DIRECTED`` when citation direction matters — since
    Leiden adds a refinement step that guarantees every community is internally
    well-connected, fixing the two Louvain weaknesses: occasionally disconnected
    communities, and a sharper exposure to the modularity resolution limit
    (Fortunato & Barthélemy 2007).

    Edge weights from ``--edge-weight-strategy`` shape the partition; citation
    direction is dropped by the symmetrisation (so it shares
    ``UNDIRECTED_BASIS_STRATEGIES`` modularity reporting with ``LEIDEN``).
    ``seed=0`` pins reproducibility — NetworkX's Louvain randomises node-visit
    order, unlike the deterministic ``leidenalg`` partitions.
    """
    communities = sorted(
        nx.community.louvain_communities(to_undirected_sum(graph), weight="weight", seed=0), key=len, reverse=True
    )
    return _finalize_partition(graph, _assign_from_node_sets(communities), palette_name, reverse=reverse)


def detect_consensus(
    graph: nx.DiGraph,
    palette_name: str,
    input_maps: dict[str, CommunityMap],
    threshold: float,
    *,
    reverse: bool = False,
) -> tuple[CommunityMap, CommunityPalette]:
    """Consensus partition over the other selected algorithmic strategies (Lancichinetti & Fortunato 2012).

    ``input_maps`` holds one :type:`CommunityMap` per consensus-eligible strategy instance
    (see :func:`consensus_eligible`) — the partitions this run already computed. The
    co-assignment matrix ``D_ij`` = the fraction of input partitions placing ``i`` and ``j``
    in the same community; pairs with ``D_ij ≥ threshold`` become the weighted, undirected
    *consensus graph*, which is clustered with Leiden modularity (``seed=0``, the same
    machinery as ``LEIDEN``). Channels grouped together only when at least a ``threshold``
    share of the algorithms agree; channels no algorithm coalition can place end up as
    singletons — an honest "no consensus" answer rather than a forced assignment.

    **Adaptation note.** Lancichinetti & Fortunato iterate — recluster ``D`` with the base
    algorithm ``n_P`` times, rebuild ``D``, repeat until block-diagonal — because their
    inputs are stochastic re-runs of one algorithm. Pulpit's input partitions are
    deterministic (every detector is seeded), so the procedure degenerates: after the first
    clustering pass the rebuilt ``D`` is exactly the 0/1 block matrix of that partition and
    every further pass is a fixed point. One pass is therefore the faithful specialisation,
    and what runs here. This is *method* consensus (different algorithms, one run each) in
    the lineage of ensemble approaches such as Evkoski et al. 2021's Ensemble Louvain,
    rather than *run* consensus.

    The result is a genuine partition: it joins the ARI/AMI/NMI/VI comparison matrices
    (measuring, e.g., how much of the analyst's label structure survives across-method
    agreement) but is excluded from the consensus balloon plot's inputs, which it would
    double-count. Weights/direction enter only through the input partitions.
    """
    if len(input_maps) < 2:
        raise ValueError(
            "CONSENSUS needs at least two consensus-eligible input partitions "
            "(algorithmic strategies other than KCORE) in --community-strategies."
        )
    node_ids, node_id_map = _node_id_index(graph)
    n_partitions = len(input_maps)
    pair_counts: Counter[tuple[int, int]] = Counter()
    for community_map in input_maps.values():
        by_community: dict[Any, list[int]] = {}
        for node_id, community_id in community_map.items():
            index = node_id_map.get(node_id)
            if index is not None:
                by_community.setdefault(community_id, []).append(index)
        for members in by_community.values():
            members.sort()
            pair_counts.update(combinations(members, 2))

    consensus_graph = ig.Graph(n=len(node_ids), directed=False)
    edges: list[tuple[int, int]] = []
    weights: list[float] = []
    for pair, count in pair_counts.items():
        agreement = count / n_partitions
        if agreement >= threshold:
            edges.append(pair)
            weights.append(agreement)
    consensus_graph.add_edges(edges)
    partition = leidenalg.find_partition(
        consensus_graph,
        leidenalg.ModularityVertexPartition,
        weights=weights if weights else None,
        seed=0,
    )
    return _finalize_partition(graph, _assign_from_partition(partition, node_ids), palette_name, reverse=reverse)


# SBM(refine=MCMC) run lengths: `wait` bounds the multiflip equilibration phase, `samples` is the
# number of posterior partitions collected for the marginals. Modest by graph-tool-docs standards
# (which use wait=1000), sized for Pulpit's few-hundred-to-few-thousand-node citation graphs.
SBM_MCMC_WAIT = 100
SBM_MCMC_SAMPLES = 100


def detect_sbm(
    graph: nx.DiGraph,
    palette_name: str,
    mode: str,
    weights: str = "",
    refine: str = "",
    *,
    reverse: bool = False,
) -> tuple[CommunityMap, CommunityPalette, "dict[str, float] | None"]:
    """Bayesian degree-corrected stochastic block model (Karrer & Newman 2011; Peixoto 2014, 2017) via graph-tool.

    Fits a **directed, degree-corrected** SBM by minimum description length. Unlike the
    modularity / CPM detectors — which only find *assortative* communities (dense-within,
    sparse-between) — the SBM recovers arbitrary block structure: assortative,
    disassortative, core-periphery and bipartite *source / amplifier* patterns alike.
    A block is a set of channels that are *stochastically equivalent* — they cite, and are
    cited by, the rest of the network the same way — i.e. a **citation-role / structural-
    equivalence class** (Lorrain & White 1971), NOT necessarily a cohesive, mutually-citing
    community. The block-affinity matrix entry is a one-step, group-to-group *direct citation
    rate*, never a transmission / flow quantity, so the strategy is consistent with the
    one-degree attribution model (see docs/community-detection.md).

    Built on the **directed** citation graph (direction preserved → asymmetric block
    affinities) and **degree-corrected**, so the partition reflects block structure *beyond*
    the in-degree heterogeneity of the star topology rather than merely re-encoding it.

    ``weights`` selects the edge model. Empty (default): **unweighted** binary citation
    structure — edge weights are not passed, so the partition is invariant to
    ``--edge-weight-strategy``, like ``KCORE``. ``POISSON`` /
    ``EXPONENTIAL`` fit a **weighted SBM** with the edge weights as covariates (Peixoto 2018,
    "Nonparametric weighted stochastic block models"): POISSON models discrete counts (pair
    with ``--edge-weight-strategy TOTAL``), EXPONENTIAL positive reals (pair with the
    ratio-valued ``PARTIAL_*`` strategies). The weight model is validated against the actual
    edge weights before graph-tool is imported.

    ``mode``: ``NESTED`` (default) fits the nested SBM (Peixoto 2017) and takes the partition
    at the bottom (finest) hierarchy level — better model selection on large graphs, avoiding
    the underfitting of the flat model; ``FLAT`` fits a single-level SBM.

    ``refine``: empty (default) reports the single MDL point estimate. ``MCMC`` follows the
    fit with multiflip MCMC equilibration and collects ``SBM_MCMC_SAMPLES`` posterior
    partitions; the reported partition is then each node's **maximum-marginal** block after
    label alignment (Peixoto 2021, "Revealing consensus and dissensus between network
    partitions", via ``PartitionModeState``), and the third return value maps each node to
    its **assignment confidence** — the share of posterior samples agreeing with the reported
    block (1.0 = the data pin the channel down; low values = structurally ambiguous). Without
    ``MCMC`` the third return value is ``None``.

    graph-tool's inference is stochastic (agglomerative + multiflip MCMC); the RNG is seeded
    for a reproducible partition. Requires the ``graph-tool`` package (conda-forge / system
    packages — it is *not* installable from pip; see docs/community-detection.md).
    """
    weights = (weights or "").upper()
    refine = (refine or "").upper()

    edge_weights: list[float] = []
    if weights:
        edge_weights = [float(graph.edges[s, t].get("weight", 1.0)) for s, t in graph.edges()]
        if weights == "POISSON":
            bad = next((w for w in edge_weights if w < 0 or not w.is_integer()), None)
            if bad is not None:
                raise ValueError(
                    "SBM(weights=POISSON) models edge weights as discrete counts, but the graph carries "
                    f"non-integer weights (e.g. {bad!r}). Use --edge-weight-strategy TOTAL (raw counts), "
                    "or switch to weights=EXPONENTIAL for the ratio-valued PARTIAL_* strategies."
                )
        elif weights == "EXPONENTIAL":
            bad = next((w for w in edge_weights if w <= 0), None)
            if bad is not None:
                raise ValueError(
                    "SBM(weights=EXPONENTIAL) models edge weights as positive reals, but the graph carries "
                    f"a non-positive weight ({bad!r}). Check --edge-weight-strategy."
                )
        else:  # defensive — parse_strategies already validated the enum
            raise ValueError(f"Unknown SBM weights model: {weights!r}. Choose POISSON or EXPONENTIAL.")

    try:
        import graph_tool.all as gt
    except ImportError as exc:  # pragma: no cover - optional heavy dependency
        raise ValueError(
            "The SBM community strategy requires the 'graph-tool' package, which is not installed. "
            "Install it via conda-forge ('conda install -c conda-forge graph-tool') or your system "
            "package manager — it is not available from pip. See docs/community-detection.md."
        ) from exc

    gt.seed_rng(0)
    node_ids, node_id_map = _node_id_index(graph)
    gt_graph = gt.Graph(directed=True)
    gt_graph.add_vertex(len(node_ids))
    state_args: dict[str, Any] = {}
    if weights:
        rec = gt_graph.new_edge_property("int" if weights == "POISSON" else "double")
        gt_graph.add_edge_list(
            [(node_id_map[s], node_id_map[t], w) for (s, t), w in zip(graph.edges(), edge_weights, strict=True)],
            eprops=[rec],
        )
        state_args = {"recs": [rec], "rec_types": ["discrete-poisson" if weights == "POISSON" else "real-exponential"]}
    else:
        gt_graph.add_edge_list([(node_id_map[s], node_id_map[t]) for s, t in graph.edges()])

    nested = mode.upper() != "FLAT"
    if nested:
        state = gt.minimize_nested_blockmodel_dl(gt_graph, state_args=state_args)
    else:
        state = gt.minimize_blockmodel_dl(gt_graph, state_args=state_args)

    confidence: dict[str, float] | None = None
    community_map: CommunityMap
    if refine == "MCMC":
        import numpy as np

        if nested:
            # Pad the hierarchy with empty levels so it can grow during sampling, and switch the
            # nested state to sampling mode — graph-tool's documented equilibration pattern.
            state = state.copy(bs=state.get_bs() + [np.zeros(1)] * 4, sampling=True)
        gt.mcmc_equilibrate(state, wait=SBM_MCMC_WAIT, mcmc_args={"niter": 10})

        partitions: list[Any] = []

        def _collect(s: Any) -> None:
            b = s.levels[0].b if nested else s.b
            partitions.append(np.asarray(b.a).copy())

        gt.mcmc_equilibrate(state, force_niter=SBM_MCMC_SAMPLES, mcmc_args={"niter": 10}, callback=_collect)
        pmode = gt.PartitionModeState(partitions, converge=True)
        marginals = pmode.get_marginal(gt_graph)
        b_max = pmode.get_max(gt_graph)
        n_samples = len(partitions)
        community_map = {}
        confidence = {}
        for index, node_id in enumerate(node_ids):
            block = int(b_max[index])
            community_map[node_id] = block
            counts = marginals[index]
            agree = counts[block] if block < len(counts) else 0
            confidence[node_id] = round(float(agree) / n_samples, 4) if n_samples else 0.0
    else:
        blocks = (state.get_levels()[0] if nested else state).get_blocks()
        community_map = {node_ids[index]: int(blocks[index]) for index in range(len(node_ids))}

    final_map, palette = _finalize_partition(graph, community_map, palette_name, reverse=reverse)
    return final_map, palette, confidence


# Zero-temperature merge-split sweeps for the planted-partition greedy fit — the value used in
# graph-tool's own PPBlockState documentation example.
PP_GREEDY_NITER = 1000


def detect_sbm_assortative(
    graph: nx.DiGraph,
    palette_name: str,
    refine: str = "",
    *,
    reverse: bool = False,
) -> tuple[CommunityMap, CommunityPalette, "dict[str, float] | None"]:
    """Bayesian planted-partition communities (Zhang & Peixoto 2020) via graph-tool's ``PPBlockState``.

    The **inferential counterpart of Leiden**: like the modularity family it looks only for
    *assortative* structure — groups denser inside than out — but as a generative model selected
    by description length it places a community boundary only where the data statistically
    support one. Zhang & Peixoto show this "succeeds in finding statistically significant
    assortative modules … unlike alternatives such as modularity maximization, which
    systematically overfits", with no resolution limit. Where ``SBM`` answers "which channels
    play the same role?", this answers Leiden's question — "where are the cohesive blocs?" —
    with statistical backing: a partition boundary that survives here is evidence, not an
    optimiser's preference. Read the two side by side in the partition-comparison matrices.

    Fitted on the **undirected W+Wᵀ projection** (assortativity is a symmetric notion — the
    same projection the Leiden family uses) and **unweighted** (binary citation structure, so
    the partition is invariant to ``--edge-weight-strategy``, like ``KCORE`` and the binary
    ``SBM``). Parameter-free and seeded: the greedy fit runs ``PP_GREEDY_NITER``
    zero-temperature merge-split sweeps, graph-tool's documented pattern.

    ``refine``: empty (default) reports the greedy point estimate. ``MCMC`` equilibrates and
    samples the posterior exactly like ``SBM(refine=MCMC)`` — the reported partition becomes
    each channel's max-marginal community and the third return value carries the per-channel
    assignment confidence (share of posterior samples agreeing); ``None`` without MCMC.

    Requires the ``graph-tool`` package (conda-forge / system packages — not pip-installable);
    a clear ``ValueError`` is raised when it is absent.
    """
    refine = (refine or "").upper()
    try:
        import graph_tool.all as gt
    except ImportError as exc:  # pragma: no cover - optional heavy dependency
        raise ValueError(
            "The SBM_ASSORTATIVE community strategy requires the 'graph-tool' package, which is not "
            "installed. Install it via conda-forge ('conda install -c conda-forge graph-tool') or your "
            "system package manager — it is not available from pip. See docs/community-detection.md."
        ) from exc

    import numpy as np

    gt.seed_rng(0)
    node_ids, node_id_map = _node_id_index(graph)
    undirected = to_undirected_sum(graph)
    gt_graph = gt.Graph(directed=False)
    gt_graph.add_vertex(len(node_ids))
    gt_graph.add_edge_list([(node_id_map[s], node_id_map[t]) for s, t in undirected.edges()])

    state = gt.PPBlockState(gt_graph)
    state.multiflip_mcmc_sweep(beta=np.inf, niter=PP_GREEDY_NITER)

    confidence: dict[str, float] | None = None
    community_map: CommunityMap
    if refine == "MCMC":
        gt.mcmc_equilibrate(state, wait=SBM_MCMC_WAIT, mcmc_args={"niter": 10})

        partitions: list[Any] = []

        def _collect(s: Any) -> None:
            partitions.append(np.asarray(s.get_blocks().a).copy())

        gt.mcmc_equilibrate(state, force_niter=SBM_MCMC_SAMPLES, mcmc_args={"niter": 10}, callback=_collect)
        pmode = gt.PartitionModeState(partitions, converge=True)
        marginals = pmode.get_marginal(gt_graph)
        b_max = pmode.get_max(gt_graph)
        n_samples = len(partitions)
        community_map = {}
        confidence = {}
        for index, node_id in enumerate(node_ids):
            block = int(b_max[index])
            community_map[node_id] = block
            marginal_counts = marginals[index]
            agree = marginal_counts[block] if block < len(marginal_counts) else 0
            confidence[node_id] = round(float(agree) / n_samples, 4) if n_samples else 0.0
    else:
        blocks = state.get_blocks()
        community_map = {node_ids[index]: int(blocks[index]) for index in range(len(node_ids))}

    final_map, palette = _finalize_partition(graph, community_map, palette_name, reverse=reverse)
    return final_map, palette, confidence


def _write_confidence(
    graph: nx.DiGraph,
    channel_dict: dict[str, Any],
    instance: "StrategyInstance",
    confidence: "dict[str, float] | None",
) -> None:
    """Attach an SBM-family ``refine=MCMC`` confidence map to the node data and channel_dict.

    The confidence companion rides on the node data like a measure column, under the instance's
    parameter-suffixed key (:func:`sbm_confidence_key`); exporters probe the nodes for its presence.
    No-op when ``confidence`` is ``None``/empty (no MCMC refinement ran).
    """
    if not confidence:
        return
    conf_key = sbm_confidence_key(instance.key)
    for node_id, value in confidence.items():
        if node_id in graph.nodes:
            graph.nodes[node_id].setdefault("data", {})[conf_key] = value
        entry = channel_dict.get(node_id)
        if entry is not None:
            entry["data"][conf_key] = value


def detect(
    instance: "StrategyInstance | str",
    palette_name: str,
    graph: nx.DiGraph,
    channel_dict: dict[str, Any],
    *,
    reverse: bool = False,
) -> tuple[CommunityMap, CommunityPalette]:
    """Run community detection for one strategy instance. Returns (community_map, community_palette).

    ``instance`` is a :class:`StrategyInstance`; a bare strategy-name string is also accepted (wrapped
    as a parameter-free instance) for convenience. The one parameterised strategy reads its tunable
    value from the instance — LEIDEN_CPM its ``resolution`` γ — falling back to the module default when
    omitted.
    """
    if isinstance(instance, str):
        instance = StrategyInstance(instance.upper())
    strategy = instance.name
    params = instance.params_dict
    if strategy == "CONSENSUS":
        # Derived from the other strategies' partitions — the export pipeline dispatches it to
        # detect_consensus() after every other strategy has run; it cannot be detected standalone.
        raise ValueError(
            "CONSENSUS is computed from the other selected strategies' partitions and is "
            "dispatched separately by the export pipeline (detect_consensus), not by detect()."
        )
    if strategy == "LEIDEN_TEMPORAL":
        # Needs every timeline year's slice at once — the export pipeline precomputes it via
        # detect_leiden_temporal() and applies the per-year / plurality maps directly.
        raise ValueError(
            "LEIDEN_TEMPORAL is computed over the per-year timeline slices and is dispatched "
            "separately by the export pipeline (detect_leiden_temporal), not by detect()."
        )
    if strategy == "KCORE":
        return detect_kcore(graph, palette_name, reverse=reverse)
    if strategy == "LEIDEN":
        return detect_leiden(graph, palette_name, reverse=reverse)
    if strategy == "LEIDEN_DIRECTED":
        return detect_leiden_directed(graph, palette_name, reverse=reverse)
    if strategy == "LEIDEN_CPM":
        return detect_leiden_cpm(
            graph, palette_name, float(params.get("resolution", CPM_DEFAULT_RESOLUTION)), reverse=reverse
        )
    if strategy == "LOUVAIN":
        return detect_louvain(graph, palette_name, reverse=reverse)
    if strategy == "SBM":
        community_map, community_palette, confidence = detect_sbm(
            graph,
            palette_name,
            str(params.get("mode", SBM_DEFAULT_MODE)),
            str(params.get("weights", "") or ""),
            str(params.get("refine", "") or ""),
            reverse=reverse,
        )
        _write_confidence(graph, channel_dict, instance, confidence)
        return community_map, community_palette
    if strategy == "SBM_ASSORTATIVE":
        community_map, community_palette, confidence = detect_sbm_assortative(
            graph,
            palette_name,
            str(params.get("refine", "") or ""),
            reverse=reverse,
        )
        _write_confidence(graph, channel_dict, instance, confidence)
        return community_map, community_palette
    gid = labelgroup_id(strategy)
    if gid is not None:
        # LABELGROUP<id> builds its palette from each Label's own colour directly, so the
        # palette_name / reverse flags don't apply.
        return detect_labelgroup(gid, channel_dict)
    raise ValueError(f"Unknown community strategy: {strategy!r}. Choose from {sorted(VALID_STRATEGIES)}.")


def apply_to_graph(
    graph: nx.DiGraph,
    channel_dict: dict[str, Any],
    community_map: CommunityMap,
    community_palette: CommunityPalette,
    strategy: "StrategyInstance | str",
) -> None:
    """Write this strategy instance's community label into each node's communities dict, plus colours.

    ``strategy`` is a :class:`StrategyInstance` (a bare name string is also accepted); the partition is
    stored under ``instance.key`` — the parameter-suffixed key for parameterised strategies, the plain
    lowercase name otherwise.
    """
    instance = strategy if isinstance(strategy, StrategyInstance) else StrategyInstance(str(strategy).upper())
    strategy_name = instance.name
    strategy_key = instance.key
    metadata = is_metadata_strategy(strategy_name)
    if metadata:
        label_ids = set(community_map.values())
        label_names = {lbl.pk: lbl.name for lbl in Label.objects.filter(pk__in=label_ids)}

    for node_id, node_data in graph.nodes(data="data"):
        community_id = community_map.get(node_id)
        if community_id is not None:
            detected_community = (
                label_names.get(community_id, str(community_id))
                if metadata
                else build_community_label(community_id, strategy_name)
            )
            node_data.setdefault("communities", {})[strategy_key] = detected_community
            channel_dict[node_id]["data"].setdefault("communities", {})[strategy_key] = detected_community
        community_color = community_palette.get(community_id) if community_id is not None else DEFAULT_FALLBACK_COLOR
        if community_color is None:
            community_color = DEFAULT_FALLBACK_COLOR
        rgb_color = ",".join(str(value) for value in community_color)
        node_data["color"] = rgb_color
        channel_dict[node_id]["data"]["color"] = rgb_color


def apply_edge_colors(graph: nx.DiGraph, edge_list: list[list[str | float]], channel_dict: dict[str, Any]) -> None:
    """Assign averaged colors to graph edges."""
    for edge in edge_list:
        source_color = channel_dict[edge[0]]["data"]["color"]
        target_color = channel_dict[edge[1]]["data"]["color"]
        color = rgb_avg(parse_color(source_color), parse_color(target_color))
        color_strs = [str(int(c * 0.75)) for c in color]
        graph.edges[edge[0], edge[1]]["color"] = ",".join(color_strs)


def build_communities_payload(
    strategies: list["StrategyInstance"],
    results: dict[str, tuple[CommunityMap, CommunityPalette]],
) -> dict[str, Any]:
    """Build the communities metadata dict for the accessory JSON file, covering all strategy instances.

    ``results`` is keyed by ``StrategyInstance.key`` (the parameter-suffixed partition key); the
    returned dict is keyed the same way.
    """
    communities_data: dict[str, Any] = {}
    for instance in strategies:
        strategy = instance.name
        strategy_key = instance.key
        community_map, community_palette = results[strategy_key]
        if strategy in COMMUNITY_ALGORITHMS:
            community_counts = Counter(community_map.values())
            groups = []
            for community_id, count in community_counts.items():
                rgb = community_palette.get(community_id, DEFAULT_FALLBACK_COLOR)
                detected_community = build_community_label(community_id, strategy)
                groups.append((str(community_id), count, detected_community, rgb_to_hex(rgb)))
            main_groups = {
                str(community_id): build_community_label(community_id, strategy) for community_id in community_counts
            }
        else:
            # LABELGROUP<id>: counts come from the resolved per-window community map (consistent with
            # node colouring), not a raw membership count — only labels that actually own a node appear.
            community_counts = Counter(community_map.values())
            label_objs = {lbl.pk: lbl for lbl in Label.objects.filter(pk__in=list(community_counts))}
            groups = [
                (label_id, count, label_objs[label_id].name, label_objs[label_id].color)
                for label_id, count in community_counts.items()
                if label_id in label_objs
            ]
            main_groups = {
                label_objs[label_id].key: label_objs[label_id].name
                for label_id in community_counts
                if label_id in label_objs
            }
        if strategy == "KCORE":
            groups = sorted(groups, key=lambda x: int(x[0]))
        else:
            groups = sorted(groups, key=lambda x: -x[1])
        communities_data[strategy_key] = {"groups": groups, "main_groups": main_groups}
    return communities_data
