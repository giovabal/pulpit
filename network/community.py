import logging
from collections import Counter
from typing import Any

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

import networkx as nx
from infomap import Infomap

logger = logging.getLogger(__name__)

COMMUNITY_ALGORITHMS = {"LOUVAIN", "KCORE", "KCORE_NATURAL", "INFOMAP"}
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
    isolated = sorted(node_id for node_id in graph.nodes() if graph.degree(node_id) == 0)
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
    # Nodes with coreness 0 (isolated) are grouped together at value 1 after normalization
    community_map: CommunityMap = {node_id: max(k, 1) for node_id, k in coreness.items()}
    community_map = normalize_community_map(community_map)
    return community_map, build_community_palette(community_map, palette_name)


def detect_kcore_natural(graph: nx.DiGraph, palette_name: str) -> tuple[CommunityMap, CommunityPalette]:
    coreness = nx.core_number(graph.to_undirected())
    unique_vals = sorted(set(max(k, 1) for k in coreness.values()))

    if len(unique_vals) == 1:
        community_map: CommunityMap = {node_id: 1 for node_id in coreness}
        return community_map, build_community_palette(community_map, palette_name)

    gaps = [unique_vals[i + 1] - unique_vals[i] for i in range(len(unique_vals) - 1)]
    # A natural gap is a missing k-shell (jump > 1 between consecutive present coreness values).
    # If all shells are consecutive (no gaps > 1), fall back to splitting at the largest gap.
    max_gap = max(gaps)
    threshold = 1 if max_gap > 1 else 0
    split_points = {unique_vals[i + 1] for i, gap in enumerate(gaps) if gap > threshold}

    cluster_id = 1
    val_to_cluster: dict[int, int] = {}
    for val in unique_vals:
        if val in split_points:
            cluster_id += 1
        val_to_cluster[val] = cluster_id

    community_map = {node_id: val_to_cluster[max(k, 1)] for node_id, k in coreness.items()}
    community_map = normalize_community_map(community_map)
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


def detect(
    strategy: str, palette_name: str, graph: nx.DiGraph, channel_dict: dict[str, Any]
) -> tuple[CommunityMap, CommunityPalette]:
    """Run community detection. Returns (community_map, community_palette)."""
    if strategy == "LOUVAIN":
        return detect_louvain(graph, palette_name)
    if strategy == "KCORE":
        return detect_kcore(graph, palette_name)
    if strategy == "KCORE_NATURAL":
        return detect_kcore_natural(graph, palette_name)
    if strategy == "INFOMAP":
        return detect_infomap(graph, palette_name)
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
        org_names = {org.pk: org.name for org in Organization.objects.filter(pk__in=set(community_map.values()))}

    for node_id, community_id in community_map.items():
        if strategy in COMMUNITY_ALGORITHMS:
            detected_community = build_community_label(community_id, strategy)
        else:
            detected_community = org_names[community_id]
        graph.nodes[node_id]["data"].setdefault("communities", {})[strategy_key] = detected_community
        channel_dict[node_id]["data"].setdefault("communities", {})[strategy_key] = detected_community

    for node_id, node_data in graph.nodes(data="data"):
        community_id = community_map.get(node_id)
        community_color: ColorTuple | None = community_palette.get(community_id) if community_id is not None else None
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
            org_qs = Organization.objects.filter(is_interesting=True)
            groups = []
            for organization in org_qs:
                groups.append(
                    (
                        organization.id,
                        organization.channel_set.count(),
                        organization.name,
                        organization.color,
                    )
                )
            main_groups = {org.key: org.name for org in org_qs}
        groups = sorted(groups, key=lambda x: -x[1])
        communities_data[strategy_key] = {"groups": groups, "main_groups": main_groups}
    return communities_data
