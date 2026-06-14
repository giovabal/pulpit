import re
from collections import Counter
from collections.abc import Iterable
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
# replacing the old fixed LEIDEN_CPM_COARSE / LEIDEN_CPM_FINE presets.
ALL_STRATEGIES: list[str] = [
    "LEIDEN",
    "LEIDEN_DIRECTED",
    "LEIDEN_CPM",
    "LOUVAIN",
    "LABELPROPAGATION",
    "KCORE",
    "SBM",
]
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


# Strategies whose partition is optimised (or computed) on the UNDIRECTED projection
# of the citation graph. Their reported modularity should use the undirected null
# model (k_i·k_j / 2m), matching what they actually optimised — not the directed
# null model (k_out_i·k_in_j / m). Keys are the lowercased community keys.
# Everything else (leiden_directed, organization) is reported with directed
# modularity, the form it was built against.
# Keys are *canonical* (parameter-suffix-stripped) strategy keys — membership is tested via
# canonical_strategy_key(), so every LEIDEN_CPM instance (whatever its resolution) is covered.
UNDIRECTED_BASIS_STRATEGIES: frozenset[str] = frozenset(
    {"leiden", "leiden_cpm", "louvain", "labelpropagation", "kcore"}
)

# Human-readable labels for the strategy keys above — mirrors STRATEGY_LABELS in
# webapp_engine/map/js/labels.js so the same display text shows up in browser
# pages and in the server-side Operations panel.
COMMUNITY_STRATEGY_LABELS: dict[str, str] = {
    "LEIDEN": "Leiden",
    "LEIDEN_DIRECTED": "Leiden directed",
    "LEIDEN_CPM": "Leiden CPM",
    "LOUVAIN": "Louvain",
    "LABELPROPAGATION": "Label propagation",
    "KCORE": "K-core",
    "SBM": "Stochastic block model",
}

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
        ),
        primary_keys=("sbm",),
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
            base = group.name if group else self.name
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
        # ALL expands to the metadata partitions first (the old ORGANIZATION-first order), then algorithms.
        all_tokens=labelgroup_tokens + ALL_STRATEGIES,
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
        return group.name if group else key
    base = canonical_strategy_key(key)
    label = COMMUNITY_STRATEGY_LABELS.get(base.upper(), base.replace("_", " ").title())
    if key == base:
        return label
    spec = PARAMETERISED_STRATEGIES.get(base.upper())
    rest = key[len(base) + 1 :]  # drop "base_" → e.g. "resolution_0_05"
    parts: list[str] = []
    for param in spec.params if spec else ():
        prefix = f"{param.name}_"
        if rest.startswith(prefix):
            raw = rest[len(prefix) :]
            value = raw.replace("_", ".") if param.kind == "float" else raw
            parts.append(f"{param.name}={value}")
            rest = ""
    return f"{label} ({', '.join(parts)})" if parts else label


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


def detect_label_propagation(
    graph: nx.DiGraph, palette_name: str, *, reverse: bool = False
) -> tuple[CommunityMap, CommunityPalette]:
    """Label propagation community detection — Cordasco & Gargano 2010 / Raghavan et al. 2007.

    Each node is initialised with a unique label; at each step every node adopts
    the most frequent label among its neighbours, with ties broken by the
    deterministic Prec-Max rule (keep the current label if it is among the
    tied top labels, otherwise pick the lexicographically largest). The
    NetworkX implementation uses the semi-synchronous variant (Cordasco &
    Gargano 2010): nodes are greedy-coloured so neighbours get different
    colours, and only same-coloured nodes update in each sweep — the
    safeguard that makes the algorithm provably terminate and avoid the
    bipartite oscillations the original asynchronous variant suffers from.
    Parameter-free, deterministic given the input, and near-linear time per
    iteration; no random seed required.

    Edge weights are not used — ``label_propagation_communities`` discards
    them, so ``--edge-weight-strategy`` does not affect the partition.
    Citation direction is also discarded: the function rejects directed
    input, so Pulpit symmetrises the graph with ``to_undirected_sum``
    (W+Wᵀ, the same projection used by ``LEIDEN``/``KCORE``
    and the reported modularity). Because weights are ignored, this yields
    the identical partition to a plain ``to_undirected()``; the W+Wᵀ choice
    is for consistency across strategies, not for effect.
    """
    communities = sorted(nx.community.label_propagation_communities(to_undirected_sum(graph)), key=len, reverse=True)
    return _finalize_partition(graph, _assign_from_node_sets(communities), palette_name, reverse=reverse)


def detect_labelgroup(group_id: int, channel_dict: dict[str, Any]) -> tuple[CommunityMap, CommunityPalette]:
    """Partition nodes by their resolved in-target label in LabelGroup ``group_id`` for the window.

    Reads the per-group window resolution ``graph_builder`` stored in ``node['group_partitions']``;
    nodes with no in-target label in the group (dead leaves, or simply unlabelled in this group) are
    left ungrouped. Community ids are ``Label`` pks and the palette is built from each label's own
    colour, so the ``palette_name`` / ``reverse`` flags don't apply (as the old ORGANIZATION strategy).
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
        weights="weight",
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


def detect_sbm(
    graph: nx.DiGraph, palette_name: str, mode: str, *, reverse: bool = False
) -> tuple[CommunityMap, CommunityPalette]:
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
    **Unweighted** (binary citation structure): edge weights are not passed, so the partition
    is invariant to ``--edge-weight-strategy`` — like ``LABELPROPAGATION`` / ``KCORE``.

    ``mode``: ``NESTED`` (default) fits the nested SBM (Peixoto 2017) and takes the partition
    at the bottom (finest) hierarchy level — better model selection on large graphs, avoiding
    the underfitting of the flat model; ``FLAT`` fits a single-level SBM.

    graph-tool's inference is stochastic (agglomerative MCMC); the RNG is seeded for a
    reproducible partition. Requires the ``graph-tool`` package (conda-forge / system packages —
    it is *not* installable from pip; see docs/community-detection.md).
    """
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
    gt_graph.add_edge_list([(node_id_map[s], node_id_map[t]) for s, t in graph.edges()])

    if mode.upper() == "FLAT":
        state = gt.minimize_blockmodel_dl(gt_graph)
        blocks = state.get_blocks()
    else:
        state = gt.minimize_nested_blockmodel_dl(gt_graph)
        blocks = state.get_levels()[0].get_blocks()

    community_map: CommunityMap = {node_ids[index]: int(blocks[index]) for index in range(len(node_ids))}
    return _finalize_partition(graph, community_map, palette_name, reverse=reverse)


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
    if strategy == "LABELPROPAGATION":
        return detect_label_propagation(graph, palette_name, reverse=reverse)
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
        return detect_sbm(graph, palette_name, str(params.get("mode", SBM_DEFAULT_MODE)), reverse=reverse)
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
