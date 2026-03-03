import logging
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

COMMUNITY_ALGORITHMS = {"LOUVAIN", "KCORE", "INFOMAP"}

type CommunityMap = dict[str, int]
type CommunityPalette = dict[int, ColorTuple]


def build_community_label(community_id: int | str, strategy: str) -> str:
    return slugify(f"{community_id}-{strategy}")


def normalize_community_map(community_map: CommunityMap) -> CommunityMap:
    community_counts: dict[int, int] = {}
    for community_id in community_map.values():
        community_counts[community_id] = community_counts.get(community_id, 0) + 1
    ordered = sorted(community_counts.items(), key=lambda item: (-item[1], item[0]))
    remap = {community_id: index for index, (community_id, _) in enumerate(ordered, start=1)}
    return {node_id: remap[community_id] for node_id, community_id in community_map.items()}


def build_community_palette(community_map: CommunityMap, palette_name: str) -> CommunityPalette:
    if not community_map:
        return {}
    total = max(community_map.values())
    group_keys = [str(index) for index in range(1, total + 1)]
    palette_values = palette_colors(palette_name)
    palette_values = expand_colors(palette_values, len(group_keys))
    palette_map: dict[str, str] = {
        group_key: ",".join(str(value) for value in parse_color(palette_color))
        for group_key, palette_color in zip(group_keys, palette_values, strict=False)
    }
    community_palette: CommunityPalette = {}
    for index in range(1, total + 1):
        palette_color = palette_map.get(str(index))
        community_palette[index] = parse_color(palette_color) if palette_color else DEFAULT_FALLBACK_COLOR
    return community_palette


def detect_louvain(graph: nx.DiGraph, palette_name: str) -> tuple[CommunityMap, CommunityPalette]:
    community_map: CommunityMap = {}
    louvain_graph = graph.to_undirected()
    communities = nx.community.louvain_communities(louvain_graph, weight="weight", seed=0)
    communities = sorted(communities, key=len, reverse=True)
    for index, community in enumerate(communities, start=1):
        for node_id in community:
            community_map[node_id] = index
    community_map = normalize_community_map(community_map)
    return community_map, build_community_palette(community_map, palette_name)


def detect_organization(channel_dict: dict[str, Any]) -> tuple[CommunityMap, CommunityPalette]:
    community_map: CommunityMap = {}
    community_palette: CommunityPalette = {}
    for channel_id, item in channel_dict.items():
        organization_id = item["channel"].organization_id
        community_map[channel_id] = organization_id
        community_palette[organization_id] = parse_color(item["channel"].organization.color)
    return community_map, community_palette


def detect_kcore(graph: nx.DiGraph, palette_name: str, k: int = 10) -> tuple[CommunityMap, CommunityPalette]:
    community_map: CommunityMap = {}
    core_graph = nx.k_core(graph.to_undirected(), k=k)
    core_nodes = set(core_graph.nodes())
    for node_id in graph.nodes():
        community_map[node_id] = 1 if node_id in core_nodes else 0
    community_map = normalize_community_map(community_map)
    return community_map, build_community_palette(community_map, palette_name)


def detect_infomap(graph: nx.DiGraph, palette_name: str) -> tuple[CommunityMap, CommunityPalette]:
    community_map: CommunityMap = {}
    infomap = Infomap("--two-level --directed")
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
            next_community += 1

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
    return detect_organization(channel_dict)


def apply_to_graph(
    graph: nx.DiGraph,
    channel_dict: dict[str, Any],
    community_map: CommunityMap,
    community_palette: CommunityPalette,
    strategy: str,
) -> None:
    """Write community labels and colors back into graph node data."""
    for node_id, community_id in community_map.items():
        detected_community = build_community_label(
            community_id if strategy in COMMUNITY_ALGORITHMS else Organization.objects.get(pk=community_id).label,
            strategy,
        )
        graph.nodes[node_id]["data"]["group"] = detected_community
        graph.nodes[node_id]["data"]["group_key"] = str(community_id)
        channel_dict[node_id]["data"]["group"] = detected_community
        channel_dict[node_id]["data"]["group_key"] = str(community_id)

    for node_id, node_data in graph.nodes(data="data"):
        group_key = node_data.get("group_key")
        community_color: ColorTuple | None = community_palette.get(int(group_key)) if group_key else None
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


def build_group_payload(
    strategy: str, community_map: CommunityMap, community_palette: CommunityPalette
) -> dict[str, Any]:
    """Build the group metadata dict for the accessory JSON file."""
    group_data: dict[str, Any] = {"groups": []}
    if strategy in COMMUNITY_ALGORITHMS:
        community_counts: dict[int, int] = {}
        for community_id in community_map.values():
            community_counts[community_id] = community_counts.get(community_id, 0) + 1
        for community_id, count in community_counts.items():
            rgb = community_palette.get(community_id, DEFAULT_FALLBACK_COLOR)
            detected_community = build_community_label(community_id, strategy)
            group_data["groups"].append((str(community_id), count, detected_community, rgb_to_hex(rgb)))
        group_data["main_groups"] = {
            str(community_id): build_community_label(community_id, strategy) for community_id in community_counts
        }
    else:
        org_qs = Organization.objects.filter(is_interesting=True)
        for organization in org_qs:
            group_data["groups"].append(
                (
                    organization.id,
                    organization.channel_set.count(),
                    organization.name.replace(", ", ""),
                    organization.color,
                )
            )
        group_data["main_groups"] = {org.key: org.name for org in org_qs}
    group_data["groups"] = sorted(group_data["groups"], key=lambda x: -x[1])
    return group_data
