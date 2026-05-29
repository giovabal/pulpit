import io
import sys
from collections import Counter
from collections.abc import Iterable
from typing import Any

from django.utils.text import slugify

from network.utils import to_undirected_sum
from webapp.models import Organization
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
import numpy as np
from infomap import Infomap

# markov_clustering writes to stderr at import time when matplotlib is absent
_stderr, sys.stderr = sys.stderr, io.StringIO()
import markov_clustering as mc  # noqa: E402

sys.stderr = _stderr
del _stderr

COMMUNITY_ALGORITHMS = {
    "LOUVAIN",
    "LABELPROPAGATION",
    "KCORE",
    "INFOMAP",
    "INFOMAP_MEMORY",
    "LEIDEN",
    "LEIDEN_DIRECTED",
    "LEIDEN_CPM_COARSE",
    "LEIDEN_CPM_FINE",
    "MCL",
    "WALKTRAP",
    "WEAKCC",
    "STRONGCC",
}
VALID_STRATEGIES = COMMUNITY_ALGORITHMS | {"ORGANIZATION"}

# Strategies whose partition is optimised (or computed) on the UNDIRECTED projection
# of the citation graph. Their reported modularity should use the undirected null
# model (k_i·k_j / 2m), matching what they actually optimised — not the directed
# null model (k_out_i·k_in_j / m). Keys are the lowercased community keys.
# Everything else (leiden_directed, infomap, infomap_memory, mcl, strongcc,
# organization) is reported with directed modularity, the form it was built against.
UNDIRECTED_BASIS_STRATEGIES: frozenset[str] = frozenset(
    {"leiden", "leiden_cpm_coarse", "leiden_cpm_fine", "louvain", "walktrap", "labelpropagation", "kcore", "weakcc"}
)

# Human-readable labels for the strategy keys above — mirrors STRATEGY_LABELS in
# webapp_engine/map/js/labels.js so the same display text shows up in browser
# pages and in the server-side Operations panel.
COMMUNITY_STRATEGY_LABELS: dict[str, str] = {
    "ORGANIZATION": "Organization",
    "LEIDEN": "Leiden",
    "LEIDEN_DIRECTED": "Leiden directed",
    "LEIDEN_CPM_COARSE": "Leiden CPM coarse",
    "LEIDEN_CPM_FINE": "Leiden CPM fine",
    "LOUVAIN": "Louvain",
    "LABELPROPAGATION": "Label propagation",
    "KCORE": "K-core",
    "INFOMAP": "Infomap",
    "INFOMAP_MEMORY": "Memory Infomap",
    "MCL": "MCL",
    "WALKTRAP": "Walktrap",
    "WEAKCC": "Weakly connected components",
    "STRONGCC": "Strongly connected components",
}

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
    the label held by the majority of its neighbours.  The NetworkX implementation
    uses the semi-synchronous variant (Cordasco & Gargano 2010), which partitions
    nodes into colour classes before each sweep to avoid oscillation.  The
    algorithm is deterministic, parameter-free, and runs in near-linear time.

    Edge weights are not used — all edges are treated equally. The graph is
    symmetrised with ``to_undirected_sum`` (the same projection the other
    undirected detectors and the reported modularity use); since the algorithm
    ignores weights this yields the identical partition to a plain
    ``to_undirected()`` while keeping the projection consistent across strategies.
    """
    communities = sorted(nx.community.label_propagation_communities(to_undirected_sum(graph)), key=len, reverse=True)
    return _finalize_partition(graph, _assign_from_node_sets(communities), palette_name, reverse=reverse)


def detect_louvain(
    graph: nx.DiGraph, palette_name: str, *, reverse: bool = False
) -> tuple[CommunityMap, CommunityPalette]:
    communities = sorted(
        nx.community.louvain_communities(to_undirected_sum(graph), weight="weight", seed=0), key=len, reverse=True
    )
    return _finalize_partition(graph, _assign_from_node_sets(communities), palette_name, reverse=reverse)


def detect_organization(channel_dict: dict[str, Any]) -> tuple[CommunityMap, CommunityPalette]:
    community_map: CommunityMap = {}
    community_palette: CommunityPalette = {}
    for channel_id, item in channel_dict.items():
        data = item["data"]
        organization_id = data.get("resolved_org_id")
        if organization_id is None:
            # Dead-leaf, or no in-target organisation in the analysis window — not grouped by organisation.
            continue
        community_map[channel_id] = organization_id
        if organization_id not in community_palette:
            community_palette[organization_id] = parse_color(data["resolved_org_color"])
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


def detect_infomap(
    graph: nx.DiGraph, palette_name: str, *, reverse: bool = False
) -> tuple[CommunityMap, CommunityPalette]:
    """First-order Infomap — Rosvall & Bergstrom (PNAS 2008); map equation Rosvall, Axelsson & Bergstrom (EPJ ST 2009).

    Minimises the map equation L(M) for a flat (``--two-level``) partition of a
    random walker on the directed citation graph. Edges keep Pulpit's as-built
    amplifier→source orientation (``--directed``, no symmetrisation); edge
    weights from ``--edge-weight-strategy`` are passed through ``addLink`` and
    shape the partition. Truly isolated nodes — those Infomap leaves out of
    every module — are folded into one fallback community so they still
    receive a label (``merge_isolated=False`` skips the usual isolated-node
    bundling because the fallback already covers them).
    """
    node_ids, node_id_map = _node_id_index(graph)
    # seed=123 pins reproducibility for parity with the other seeded detectors
    # (Leiden/Louvain seed=0, Memory Infomap seed=123); it matches Infomap's own
    # current default but makes the run independent of that default ever changing.
    infomap = Infomap("--two-level --directed --silent", seed=123)
    for source, target, edge_data in graph.edges(data=True):
        infomap.addLink(node_id_map[source], node_id_map[target], edge_data.get("weight", 1.0))

    infomap.run()
    module_ids: dict[str, int] = {node_ids[node.node_id]: node.module_id for node in infomap.nodes}

    community_map: CommunityMap = {}
    if module_ids:
        module_map = {module_id: index for index, module_id in enumerate(sorted(set(module_ids.values())), start=1)}
        community_map = {node_id: module_map[module_id] for node_id, module_id in module_ids.items()}

    next_community = max(community_map.values(), default=0) + 1
    for node_id in node_ids:
        if node_id not in community_map:
            community_map[node_id] = next_community

    return _finalize_partition(graph, community_map, palette_name, reverse=reverse, merge_isolated=False)


def detect_weakcc(
    graph: nx.DiGraph, palette_name: str, *, reverse: bool = False
) -> tuple[CommunityMap, CommunityPalette]:
    components = sorted(nx.weakly_connected_components(graph), key=len, reverse=True)
    return _finalize_partition(
        graph, _assign_from_node_sets(components), palette_name, reverse=reverse, merge_isolated=False
    )


def detect_strongcc(
    graph: nx.DiGraph, palette_name: str, *, reverse: bool = False
) -> tuple[CommunityMap, CommunityPalette]:
    components = sorted(nx.strongly_connected_components(graph), key=len, reverse=True)
    return _finalize_partition(
        graph, _assign_from_node_sets(components), palette_name, reverse=reverse, merge_isolated=False
    )


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


def detect_mcl(
    graph: nx.DiGraph, palette_name: str, inflation: float, *, reverse: bool = False
) -> tuple[CommunityMap, CommunityPalette]:
    """Markov Clustering (MCL) — van Dongen 2000.

    Works natively on the directed weighted graph: alternates matrix expansion
    (random-walk diffusion) and inflation (contrast enhancement) until
    convergence.  The ``inflation`` parameter controls granularity: higher
    values produce more, smaller communities.
    """
    node_ids, node_id_map = _node_id_index(graph)
    n = len(node_ids)
    matrix = np.zeros((n, n), dtype=float)
    for source, target, edge_data in graph.edges(data=True):
        matrix[node_id_map[source], node_id_map[target]] = edge_data.get("weight", 1.0)

    # Give isolated nodes a self-loop so the stochastic matrix stays well-defined.
    for i in range(n):
        if matrix[i].sum() == 0 and matrix[:, i].sum() == 0:
            matrix[i, i] = 1.0

    clusters = mc.get_clusters(mc.run_mcl(matrix, inflation=inflation))
    community_map = _assign_from_partition(clusters, node_ids)

    # Nodes not placed in any cluster (edge cases in sparse graphs) → singletons.
    assigned: set[int] = {idx for cluster in clusters for idx in cluster}
    next_id = len(clusters) + 1
    for i, node_id in enumerate(node_ids):
        if i not in assigned:
            community_map[node_id] = next_id
            next_id += 1

    return _finalize_partition(graph, community_map, palette_name, reverse=reverse, merge_isolated=False)


def detect_infomap_memory(
    graph: nx.DiGraph, palette_name: str, *, reverse: bool = False
) -> tuple[CommunityMap, CommunityPalette]:
    """Second-order (memory) Infomap — Rosvall et al., Nature Communications 2014.

    Builds a higher-order state network: each state node represents the context
    "currently at channel B, having arrived from channel A".  The random walker
    then follows the outgoing edges of B weighted by their actual citation
    frequencies.  This captures sequential forwarding patterns that first-order
    Infomap treats as independent.  Channels with no incoming edges receive a
    virtual entry state so they participate in the flow.
    """
    community_map: CommunityMap = {}
    node_ids, node_id_map = _node_id_index(graph)
    n = len(node_ids)

    infomap = Infomap("--two-level --directed --silent --recorded-teleportation", seed=123)

    # State node for edge A→B: state_id = idx_A * n + idx_B, physical node = idx_B.
    for src, tgt in graph.edges():
        infomap.add_state_node(node_id_map[src] * n + node_id_map[tgt], node_id_map[tgt])

    # Virtual entry state for source nodes (no incoming edges, would be unreachable).
    _virtual_base = n * n
    for node_id in node_ids:
        node_idx = node_id_map[node_id]
        if graph.in_degree(node_id) == 0 and graph.out_degree(node_id) > 0:
            infomap.add_state_node(_virtual_base + node_idx, node_idx)

    # Trigram links: state(A→B) → state(B→C) with weight w(B→C).
    for mid in node_ids:
        mid_idx = node_id_map[mid]
        predecessors = list(graph.predecessors(mid))
        successors = list(graph.successors(mid))
        if not successors:
            continue
        # Incoming state IDs: edge-states plus virtual entry if source node.
        if predecessors:
            in_states = [node_id_map[src] * n + mid_idx for src in predecessors]
        else:
            in_states = [_virtual_base + mid_idx]
        for tgt in successors:
            tgt_idx = node_id_map[tgt]
            weight = graph.edges[mid, tgt].get("weight", 1.0)
            state_out = mid_idx * n + tgt_idx
            for state_in in in_states:
                infomap.add_link(state_in, state_out, weight)

    infomap.run()

    # Aggregate state-node module assignments to physical nodes (plurality vote).
    physical_modules: dict[int, list[int]] = {}
    for node in infomap.nodes:
        physical_modules.setdefault(node.node_id, []).append(node.module_id)

    for phys_idx, modules in physical_modules.items():
        community_map[node_ids[phys_idx]] = Counter(modules).most_common(1)[0][0]

    # Isolated nodes with no state nodes at all → singleton fallback.
    next_id = max(community_map.values(), default=0) + 1
    for node_id in node_ids:
        if node_id not in community_map:
            community_map[node_id] = next_id
            next_id += 1

    return _finalize_partition(graph, community_map, palette_name, reverse=reverse, merge_isolated=False)


def detect_walktrap(
    graph: nx.DiGraph, palette_name: str, *, reverse: bool = False
) -> tuple[CommunityMap, CommunityPalette]:
    """Walktrap community detection — Pons & Latapy 2005.

    Computes short random-walk distances between nodes (default 4 steps): two
    nodes are considered similar if a random walker starting at one tends to
    visit the other within a few hops.  Ward's agglomerative clustering is then
    applied to these distances, producing a full dendrogram that is cut at the
    partition maximising modularity.

    The graph is symmetrised to undirected before clustering (same as LEIDEN).
    """
    node_ids, node_id_map = _node_id_index(graph)
    ig_graph, weights = _build_undirected_igraph(graph, node_ids, node_id_map)
    if weights:
        ig_graph.es["weight"] = weights
    partition = ig_graph.community_walktrap(weights="weight" if weights else None, steps=4).as_clustering()
    return _finalize_partition(graph, _assign_from_partition(partition, node_ids), palette_name, reverse=reverse)


def detect(
    strategy: str,
    palette_name: str,
    graph: nx.DiGraph,
    channel_dict: dict[str, Any],
    *,
    reverse: bool = False,
    leiden_coarse_resolution: float = 0.01,
    leiden_fine_resolution: float = 0.05,
    mcl_inflation: float = 2.0,
) -> tuple[CommunityMap, CommunityPalette]:
    """Run community detection. Returns (community_map, community_palette)."""
    if strategy == "LABELPROPAGATION":
        return detect_label_propagation(graph, palette_name, reverse=reverse)
    if strategy == "LOUVAIN":
        return detect_louvain(graph, palette_name, reverse=reverse)
    if strategy == "KCORE":
        return detect_kcore(graph, palette_name, reverse=reverse)
    if strategy == "INFOMAP":
        return detect_infomap(graph, palette_name, reverse=reverse)
    if strategy == "INFOMAP_MEMORY":
        return detect_infomap_memory(graph, palette_name, reverse=reverse)
    if strategy == "LEIDEN":
        return detect_leiden(graph, palette_name, reverse=reverse)
    if strategy == "LEIDEN_DIRECTED":
        return detect_leiden_directed(graph, palette_name, reverse=reverse)
    if strategy == "LEIDEN_CPM_COARSE":
        return detect_leiden_cpm(graph, palette_name, leiden_coarse_resolution, reverse=reverse)
    if strategy == "LEIDEN_CPM_FINE":
        return detect_leiden_cpm(graph, palette_name, leiden_fine_resolution, reverse=reverse)
    if strategy == "MCL":
        return detect_mcl(graph, palette_name, mcl_inflation, reverse=reverse)
    if strategy == "WALKTRAP":
        return detect_walktrap(graph, palette_name, reverse=reverse)
    if strategy == "WEAKCC":
        return detect_weakcc(graph, palette_name, reverse=reverse)
    if strategy == "STRONGCC":
        return detect_strongcc(graph, palette_name, reverse=reverse)
    if strategy == "ORGANIZATION":
        # ORGANIZATION builds its palette from Organization.color directly, so the
        # palette_name / reverse flags don't apply.
        return detect_organization(channel_dict)
    raise ValueError(f"Unknown community strategy: {strategy!r}. Choose from {sorted(VALID_STRATEGIES)}.")


def apply_to_graph(
    graph: nx.DiGraph,
    channel_dict: dict[str, Any],
    community_map: CommunityMap,
    community_palette: CommunityPalette,
    strategy: str,
) -> None:
    """Write community label for this strategy into the communities dict on each node, and update node colors."""
    strategy_key = strategy.lower()
    if strategy not in COMMUNITY_ALGORITHMS:
        org_ids = set(community_map.values())
        org_names = {org.pk: org.name for org in Organization.objects.filter(pk__in=org_ids)}

    for node_id, node_data in graph.nodes(data="data"):
        community_id = community_map.get(node_id)
        if community_id is not None:
            detected_community = (
                build_community_label(community_id, strategy)
                if strategy in COMMUNITY_ALGORITHMS
                else org_names.get(community_id, str(community_id))
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
    strategies: list[str],
    results: dict[str, tuple[CommunityMap, CommunityPalette]],
) -> dict[str, Any]:
    """Build the communities metadata dict for the accessory JSON file, covering all strategies."""
    communities_data: dict[str, Any] = {}
    for strategy in strategies:
        community_map, community_palette = results[strategy]
        strategy_key = strategy.lower()
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
            # ORGANIZATION: counts come from the resolved per-window community map (consistent with
            # node colouring), not a raw FK channel count — only orgs that actually own a node appear.
            community_counts = Counter(community_map.values())
            org_objs = {o.pk: o for o in Organization.objects.filter(pk__in=list(community_counts))}
            groups = [
                (org_id, count, org_objs[org_id].name, org_objs[org_id].color)
                for org_id, count in community_counts.items()
                if org_id in org_objs
            ]
            main_groups = {
                org_objs[org_id].key: org_objs[org_id].name for org_id in community_counts if org_id in org_objs
            }
        if strategy == "KCORE":
            groups = sorted(groups, key=lambda x: int(x[0]))
        else:
            groups = sorted(groups, key=lambda x: -x[1])
        communities_data[strategy_key] = {"groups": groups, "main_groups": main_groups}
    return communities_data
