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
import networkx as nx
from infomap import Infomap

logger = logging.getLogger(__name__)

COMMUNITY_ALGORITHMS = {"LOUVAIN", "KCORE", "INFOMAP", "LEIDEN", "LEIDEN_DIRECTED", "WEAKCC", "STRONGCC"}
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
    edges = [(node_id_map[s], node_id_map[t]) for s, t in undirected.edges()]
    weights = [undirected.edges[s, t].get("weight", 1.0) for s, t in undirected.edges()]
    ig_graph.add_edges(edges)

    partition = leidenalg.find_partition(
        ig_graph,
        leidenalg.ModularityVertexPartition,
        weights=weights if weights else None,
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


def detect(
    strategy: str, palette_name: str, graph: nx.DiGraph, channel_dict: dict[str, Any]
) -> tuple[CommunityMap, CommunityPalette]:
    """Run community detection. Returns (community_map, community_palette)."""
    if strategy == "LOUVAIN":
        return detect_louvain(graph, palette_name)
    if strategy == "KCORE":
        return detect_kcore(graph, palette_name)
    if strategy == "INFOMAP":
        return detect_infomap(graph, palette_name)
    if strategy == "LEIDEN":
        return detect_leiden(graph, palette_name)
    if strategy == "LEIDEN_DIRECTED":
        return detect_leiden_directed(graph, palette_name)
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
