import logging
from collections import Counter
from typing import Any

from django.db.models import Count
from django.utils.text import slugify

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
import markov_clustering as mc
import networkx as nx
import numpy as np
from infomap import Infomap

logger = logging.getLogger(__name__)

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

type CommunityMap = dict[str, int]
type CommunityPalette = dict[int, ColorTuple]


def build_community_label(community_id: int | str, strategy: str) -> str:
    return slugify(f"{community_id}-{strategy}")


def normalize_community_map(community_map: CommunityMap) -> CommunityMap:
    community_counts = Counter(community_map.values())
    ordered = sorted(community_counts.items(), key=lambda item: (-item[1], item[0]))
    remap = {community_id: index for index, (community_id, _) in enumerate(ordered, start=1)}
    return {node_id: remap[community_id] for node_id, community_id in community_map.items()}


def build_community_palette(community_map: CommunityMap, palette_name: str) -> CommunityPalette:
    if not community_map:
        return {}
    total = max(community_map.values())
    colors = expand_colors(palette_colors(palette_name), total)
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


def detect_label_propagation(graph: nx.DiGraph, palette_name: str) -> tuple[CommunityMap, CommunityPalette]:
    """Label propagation community detection — Cordasco & Gargano 2010 / Raghavan et al. 2007.

    Each node is initialised with a unique label; at each step every node adopts
    the label held by the majority of its neighbours.  The NetworkX implementation
    uses the semi-synchronous variant (Cordasco & Gargano 2010), which partitions
    nodes into colour classes before each sweep to avoid oscillation.  The
    algorithm is deterministic, parameter-free, and runs in near-linear time.

    Edge weights are not used — all edges are treated equally.
    The graph is symmetrised to undirected before running.
    """
    community_map: CommunityMap = {}
    undirected = graph.to_undirected()
    communities = nx.community.label_propagation_communities(undirected)
    communities = sorted(communities, key=len, reverse=True)
    for index, community in enumerate(communities, start=1):
        for node_id in community:
            community_map[node_id] = index
    community_map = _merge_isolated_nodes(graph, community_map)
    community_map = normalize_community_map(community_map)
    return community_map, build_community_palette(community_map, palette_name)


def detect_louvain(graph: nx.DiGraph, palette_name: str) -> tuple[CommunityMap, CommunityPalette]:
    community_map: CommunityMap = {}
    louvain_graph = graph.to_undirected()
    communities = nx.community.louvain_communities(louvain_graph, weight="weight", seed=0)
    communities = sorted(communities, key=len, reverse=True)
    for index, community in enumerate(communities, start=1):
        for node_id in community:
            community_map[node_id] = index
    community_map = _merge_isolated_nodes(graph, community_map)
    community_map = normalize_community_map(community_map)
    return community_map, build_community_palette(community_map, palette_name)


def detect_organization(channel_dict: dict[str, Any]) -> tuple[CommunityMap, CommunityPalette]:
    community_map: CommunityMap = {}
    community_palette: CommunityPalette = {}
    for channel_id, item in channel_dict.items():
        channel = item["channel"]
        organization_id = channel.organization_id
        if organization_id is None:
            logger.warning("Channel %s has no organization; skipping community assignment", channel_id)
            continue
        community_map[channel_id] = organization_id
        if organization_id not in community_palette:
            community_palette[organization_id] = parse_color(channel.organization.color)
    return community_map, community_palette


def detect_kcore(graph: nx.DiGraph, palette_name: str) -> tuple[CommunityMap, CommunityPalette]:
    coreness = nx.core_number(graph.to_undirected())
    # Nodes with coreness 0 (isolated) are grouped together at shell 1
    raw: CommunityMap = {node_id: max(k, 1) for node_id, k in coreness.items()}
    # Assign community IDs ordered from most internal (highest k-shell) to outermost
    shells = sorted(set(raw.values()), reverse=True)
    remap = {shell: index for index, shell in enumerate(shells, start=1)}
    community_map: CommunityMap = {node_id: remap[shell] for node_id, shell in raw.items()}
    return community_map, build_community_palette(community_map, palette_name)


def detect_infomap(graph: nx.DiGraph, palette_name: str) -> tuple[CommunityMap, CommunityPalette]:
    community_map: CommunityMap = {}
    infomap = Infomap("--two-level --directed --silent")
    node_ids: list[str] = sorted(graph.nodes())
    node_id_map = {node_id: index for index, node_id in enumerate(node_ids)}
    for source, target, edge_data in graph.edges(data=True):
        weight = edge_data.get("weight", 1.0)
        infomap.addLink(node_id_map[source], node_id_map[target], weight)

    infomap.run()
    module_ids: dict[str, int] = {}
    for node in infomap.nodes:
        original_id = node_ids[node.node_id]
        module_ids[original_id] = node.module_id

    if module_ids:
        module_map = {module_id: index for index, module_id in enumerate(sorted(set(module_ids.values())), start=1)}
        for node_id, module_id in module_ids.items():
            community_map[node_id] = module_map[module_id]

    next_community = max(community_map.values(), default=0) + 1
    for node_id in node_ids:
        if node_id not in community_map:
            community_map[node_id] = next_community

    community_map = normalize_community_map(community_map)
    return community_map, build_community_palette(community_map, palette_name)


def detect_weakcc(graph: nx.DiGraph, palette_name: str) -> tuple[CommunityMap, CommunityPalette]:
    community_map: CommunityMap = {}
    components = sorted(nx.weakly_connected_components(graph), key=len, reverse=True)
    for index, component in enumerate(components, start=1):
        for node_id in component:
            community_map[node_id] = index
    community_map = normalize_community_map(community_map)
    return community_map, build_community_palette(community_map, palette_name)


def detect_strongcc(graph: nx.DiGraph, palette_name: str) -> tuple[CommunityMap, CommunityPalette]:
    community_map: CommunityMap = {}
    components = sorted(nx.strongly_connected_components(graph), key=len, reverse=True)
    for index, component in enumerate(components, start=1):
        for node_id in component:
            community_map[node_id] = index
    community_map = normalize_community_map(community_map)
    return community_map, build_community_palette(community_map, palette_name)


def detect_leiden(graph: nx.DiGraph, palette_name: str) -> tuple[CommunityMap, CommunityPalette]:
    community_map: CommunityMap = {}
    node_ids: list[str] = sorted(graph.nodes())
    node_id_map = {node_id: index for index, node_id in enumerate(node_ids)}

    undirected = graph.to_undirected(reciprocal=False)
    ig_graph = ig.Graph(n=len(node_ids), directed=False)
    edges, weights = [], []
    for s, t in undirected.edges():
        edges.append((node_id_map[s], node_id_map[t]))
        weights.append(undirected.edges[s, t].get("weight", 1.0))
    ig_graph.add_edges(edges)
    if weights:
        ig_graph.es["weight"] = weights

    partition = leidenalg.find_partition(
        ig_graph,
        leidenalg.ModularityVertexPartition,
        weights="weight" if weights else None,
        seed=0,
    )

    for community_index, community in enumerate(partition, start=1):
        for node_index in community:
            community_map[node_ids[node_index]] = community_index

    community_map = _merge_isolated_nodes(graph, community_map)
    community_map = normalize_community_map(community_map)
    return community_map, build_community_palette(community_map, palette_name)


def detect_leiden_directed(graph: nx.DiGraph, palette_name: str) -> tuple[CommunityMap, CommunityPalette]:
    """Directed modularity (Leicht & Newman 2008) via leidenalg.

    Uses ModularityVertexPartition on a directed igraph so the null model is
    k_out_i * k_in_j / m rather than the undirected k_i * k_j / (2m).
    Communities are built from asymmetric citation patterns: a source that
    cites many channels without being cited back is treated differently from
    a target that is widely cited.  Edge direction is preserved throughout
    the optimisation.
    """
    community_map: CommunityMap = {}
    node_ids: list[str] = sorted(graph.nodes())
    node_id_map = {node_id: index for index, node_id in enumerate(node_ids)}

    ig_graph = ig.Graph(n=len(node_ids), directed=True)
    edges = [(node_id_map[s], node_id_map[t]) for s, t in graph.edges()]
    weights = [graph.edges[s, t].get("weight", 1.0) for s, t in graph.edges()]
    ig_graph.add_edges(edges)
    if weights:
        ig_graph.es["weight"] = weights

    partition = leidenalg.find_partition(
        ig_graph,
        leidenalg.ModularityVertexPartition,
        weights="weight",
        seed=0,
    )

    for community_index, community in enumerate(partition, start=1):
        for node_index in community:
            community_map[node_ids[node_index]] = community_index

    community_map = _merge_isolated_nodes(graph, community_map)
    community_map = normalize_community_map(community_map)
    return community_map, build_community_palette(community_map, palette_name)


def _build_undirected_igraph(
    graph: nx.DiGraph, node_ids: list[str], node_id_map: dict[str, int]
) -> tuple[ig.Graph, list[float]]:
    """Build an undirected igraph from a NetworkX DiGraph, symmetrising edges."""
    undirected = graph.to_undirected(reciprocal=False)
    ig_graph = ig.Graph(n=len(node_ids), directed=False)
    edges, weights = [], []
    for s, t in undirected.edges():
        edges.append((node_id_map[s], node_id_map[t]))
        weights.append(undirected.edges[s, t].get("weight", 1.0))
    ig_graph.add_edges(edges)
    return ig_graph, weights


def detect_leiden_cpm(graph: nx.DiGraph, palette_name: str, resolution: float) -> tuple[CommunityMap, CommunityPalette]:
    """Leiden algorithm with Constant Potts Model (CPM) objective.

    Unlike modularity, CPM has no resolution limit: communities are defined as
    groups whose internal edge density exceeds ``resolution``.  A low resolution
    gives a coarse partition (few large communities); a high resolution gives a
    fine partition (many small ones).

    The graph is symmetrised to undirected before optimisation (same as LEIDEN).
    """
    community_map: CommunityMap = {}
    node_ids: list[str] = sorted(graph.nodes())
    node_id_map = {node_id: index for index, node_id in enumerate(node_ids)}
    ig_graph, weights = _build_undirected_igraph(graph, node_ids, node_id_map)

    partition = leidenalg.find_partition(
        ig_graph,
        leidenalg.CPMVertexPartition,
        weights=weights if weights else None,
        resolution_parameter=resolution,
        seed=0,
    )

    for community_index, community in enumerate(partition, start=1):
        for node_index in community:
            community_map[node_ids[node_index]] = community_index

    community_map = _merge_isolated_nodes(graph, community_map)
    community_map = normalize_community_map(community_map)
    return community_map, build_community_palette(community_map, palette_name)


def detect_mcl(graph: nx.DiGraph, palette_name: str, inflation: float) -> tuple[CommunityMap, CommunityPalette]:
    """Markov Clustering (MCL) — van Dongen 2000.

    Works natively on the directed weighted graph: alternates matrix expansion
    (random-walk diffusion) and inflation (contrast enhancement) until
    convergence.  The ``inflation`` parameter controls granularity: higher
    values produce more, smaller communities.
    """
    community_map: CommunityMap = {}
    node_ids: list[str] = sorted(graph.nodes())
    n = len(node_ids)
    node_id_map = {node_id: index for index, node_id in enumerate(node_ids)}

    matrix = np.zeros((n, n), dtype=float)
    for source, target, edge_data in graph.edges(data=True):
        matrix[node_id_map[source], node_id_map[target]] = edge_data.get("weight", 1.0)

    # Give isolated nodes a self-loop so the stochastic matrix stays well-defined.
    for i in range(n):
        if matrix[i].sum() == 0 and matrix[:, i].sum() == 0:
            matrix[i, i] = 1.0

    result = mc.run_mcl(matrix, inflation=inflation)
    clusters = mc.get_clusters(result)

    assigned: set[int] = set()
    for community_index, cluster in enumerate(clusters, start=1):
        for node_index in cluster:
            community_map[node_ids[node_index]] = community_index
            assigned.add(node_index)

    # Nodes not placed in any cluster (edge cases in sparse graphs) → singletons.
    next_id = len(clusters) + 1
    for i, node_id in enumerate(node_ids):
        if i not in assigned:
            community_map[node_id] = next_id
            next_id += 1

    community_map = normalize_community_map(community_map)
    return community_map, build_community_palette(community_map, palette_name)


def detect_infomap_memory(graph: nx.DiGraph, palette_name: str) -> tuple[CommunityMap, CommunityPalette]:
    """Second-order (memory) Infomap — Rosvall et al., Nature Communications 2014.

    Builds a higher-order state network: each state node represents the context
    "currently at channel B, having arrived from channel A".  The random walker
    then follows the outgoing edges of B weighted by their actual citation
    frequencies.  This captures sequential forwarding patterns that first-order
    Infomap treats as independent.  Channels with no incoming edges receive a
    virtual entry state so they participate in the flow.
    """
    community_map: CommunityMap = {}
    node_ids: list[str] = sorted(graph.nodes())
    n = len(node_ids)
    node_id_map = {node_id: index for index, node_id in enumerate(node_ids)}

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

    community_map = normalize_community_map(community_map)
    return community_map, build_community_palette(community_map, palette_name)


def detect_walktrap(graph: nx.DiGraph, palette_name: str) -> tuple[CommunityMap, CommunityPalette]:
    """Walktrap community detection — Pons & Latapy 2005.

    Computes short random-walk distances between nodes (default 4 steps): two
    nodes are considered similar if a random walker starting at one tends to
    visit the other within a few hops.  Ward's agglomerative clustering is then
    applied to these distances, producing a full dendrogram that is cut at the
    partition maximising modularity.

    The graph is symmetrised to undirected before clustering (same as LEIDEN).
    """
    community_map: CommunityMap = {}
    node_ids: list[str] = sorted(graph.nodes())
    node_id_map = {node_id: index for index, node_id in enumerate(node_ids)}
    ig_graph, weights = _build_undirected_igraph(graph, node_ids, node_id_map)

    if weights:
        ig_graph.es["weight"] = weights

    dendrogram = ig_graph.community_walktrap(weights="weight" if weights else None, steps=4)
    partition = dendrogram.as_clustering()

    for community_index, community in enumerate(partition, start=1):
        for node_index in community:
            community_map[node_ids[node_index]] = community_index

    community_map = _merge_isolated_nodes(graph, community_map)
    community_map = normalize_community_map(community_map)
    return community_map, build_community_palette(community_map, palette_name)


def detect(
    strategy: str,
    palette_name: str,
    graph: nx.DiGraph,
    channel_dict: dict[str, Any],
    *,
    leiden_coarse_resolution: float = 0.01,
    leiden_fine_resolution: float = 0.05,
    mcl_inflation: float = 2.0,
) -> tuple[CommunityMap, CommunityPalette]:
    """Run community detection. Returns (community_map, community_palette)."""
    if strategy == "LABELPROPAGATION":
        return detect_label_propagation(graph, palette_name)
    if strategy == "LOUVAIN":
        return detect_louvain(graph, palette_name)
    if strategy == "KCORE":
        return detect_kcore(graph, palette_name)
    if strategy == "INFOMAP":
        return detect_infomap(graph, palette_name)
    if strategy == "INFOMAP_MEMORY":
        return detect_infomap_memory(graph, palette_name)
    if strategy == "LEIDEN":
        return detect_leiden(graph, palette_name)
    if strategy == "LEIDEN_DIRECTED":
        return detect_leiden_directed(graph, palette_name)
    if strategy == "LEIDEN_CPM_COARSE":
        return detect_leiden_cpm(graph, palette_name, leiden_coarse_resolution)
    if strategy == "LEIDEN_CPM_FINE":
        return detect_leiden_cpm(graph, palette_name, leiden_fine_resolution)
    if strategy == "MCL":
        return detect_mcl(graph, palette_name, mcl_inflation)
    if strategy == "WALKTRAP":
        return detect_walktrap(graph, palette_name)
    if strategy == "WEAKCC":
        return detect_weakcc(graph, palette_name)
    if strategy == "STRONGCC":
        return detect_strongcc(graph, palette_name)
    if strategy == "ORGANIZATION":
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
                else org_names[community_id]
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
            orgs = list(Organization.objects.filter(is_interesting=True).annotate(channel_count=Count("channel")))
            groups = [(org.id, org.channel_count, org.name, org.color) for org in orgs]
            main_groups = {org.key: org.name for org in orgs}
        if strategy == "KCORE":
            groups = sorted(groups, key=lambda x: int(x[0]))
        else:
            groups = sorted(groups, key=lambda x: -x[1])
        communities_data[strategy_key] = {"groups": groups, "main_groups": main_groups}
    return communities_data
