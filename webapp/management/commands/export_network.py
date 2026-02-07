import colorsys
import json
import os
import shutil
from math import sqrt

from django.conf import settings
from django.core.management.base import BaseCommand
from django.db.models import Q

from webapp.models import Channel, Organization
from webapp_engine.utils import hex_to_rgb, rgb_avg, rgb_to_hex

import networkx as nx
import pypalettes
from infomap import Infomap
from pyforceatlas2 import ForceAtlas2

DEFAULT_FALLBACK_COLOR = (204, 204, 204)


def parse_color(value):
    if isinstance(value, (list, tuple)):
        return tuple(int(part) for part in value[:3])
    if isinstance(value, str):
        cleaned = value.strip()
        if cleaned.lower().startswith("rgb"):
            channel_values = cleaned[cleaned.find("(") + 1 : cleaned.rfind(")")].split(",")
            parsed = [float(part.strip()) for part in channel_values if part.strip()]
            if not parsed:
                return DEFAULT_FALLBACK_COLOR
            if parsed and max(parsed) <= 1:
                return tuple(int(part * 255) for part in parsed[:3])
            return tuple(int(part) for part in parsed[:3])
        if "," in cleaned:
            return tuple(int(part.strip()) for part in cleaned.split(","))
        if " " in cleaned:
            parts = [part for part in cleaned.split(" ") if part]
            if len(parts) >= 3 and all(part.replace(".", "", 1).isdigit() for part in parts[:3]):
                parsed = [float(part) for part in parts[:3]]
                if parsed and max(parsed) <= 1:
                    return tuple(int(part * 255) for part in parsed[:3])
                return tuple(int(part) for part in parsed[:3])
        if cleaned.lower().startswith("0x"):
            cleaned = cleaned[2:]
        try:
            return hex_to_rgb(cleaned)
        except ValueError:
            return DEFAULT_FALLBACK_COLOR
    return DEFAULT_FALLBACK_COLOR


def palette_colors(name):
    palette = None
    if hasattr(pypalettes, "load_palette"):
        palette = pypalettes.load_palette(name)
    elif hasattr(pypalettes, "get_palette"):
        palette = pypalettes.get_palette(name)
    elif hasattr(pypalettes, "Palette"):
        palette = pypalettes.Palette(name)
    if palette is None:
        raise ValueError(f"Palette '{name}' could not be loaded.")

    colors = None
    for attr in ("colors", "hex_colors", "palette", "hex"):
        if hasattr(palette, attr):
            colors = getattr(palette, attr)
            break
    if colors is None:
        colors = palette
    if not isinstance(colors, (list, tuple)):
        colors = list(colors)
    return colors


def expand_colors(colors, count):
    if not colors:
        return []
    if len(colors) >= count:
        return list(colors[:count])
    repeats = (count + len(colors) - 1) // len(colors)
    return (list(colors) * repeats)[:count]


def colors_for_groups(group_keys):
    palette_values = palette_colors(settings.COMMUNITIES_PALETTE)
    palette_values = expand_colors(palette_values, len(group_keys))
    return {
        group_key: ",".join(str(value) for value in parse_color(palette_color))
        for group_key, palette_color in zip(group_keys, palette_values, strict=False)
    }


def average_color(colors):
    if not colors:
        return DEFAULT_FALLBACK_COLOR
    totals = [0, 0, 0]
    for color in colors:
        for index, value in enumerate(parse_color(color)):
            totals[index] += value
    count = len(colors)
    return tuple(int(total / count) for total in totals)


def build_graph():
    graph = nx.DiGraph()
    channel_dict = {}
    qs_filter = Q(organization__is_interesting=True)
    if settings.DRAW_DEAD_LEAVES:
        qs_filter |= Q(in_degree__gt=0)
    qs = Channel.objects.filter(qs_filter)
    for channel in qs:
        channel_dict[str(channel.pk)] = {"channel": channel, "data": channel.network_data()}
        graph.add_node(str(channel.pk), data=channel_dict[str(channel.pk)]["data"])
    return graph, channel_dict, qs


def build_edge_list(channel_dict):
    edge_list = []
    for source_id, source_data in channel_dict.items():
        for target_id, target_data in channel_dict.items():
            if source_id == target_id:
                continue
            message_count = target_data["channel"].message_set.all().count()
            weight = (
                0
                if not message_count
                else (
                    target_data["channel"].message_set.filter(forwarded_from=source_data["channel"]).count()
                    + source_data["channel"].reference_message_set.filter(channel=target_data["channel"]).count()
                )
                / message_count
            )
            if weight > 0:
                color = rgb_avg(
                    parse_color(
                        source_data["data"]["color"]
                        if source_data["channel"].organization
                        else settings.DEAD_LEAVES_COLOR
                    ),
                    parse_color(
                        target_data["data"]["color"]
                        if target_data["channel"].organization
                        else settings.DEAD_LEAVES_COLOR
                    ),
                )
                color = [str(int(c * 0.75)) for c in color]
                edge_list.append(
                    [str(target_data["channel"].pk), str(source_data["channel"].pk), weight, ",".join(color)]
                )
    return edge_list


def add_edges_to_graph(graph, edge_list):
    max_weight = max(edge[2] for edge in edge_list)
    for edge in edge_list:
        graph.add_edge(edge[0], edge[1], weight=max(10 * edge[2] / max_weight, 0.0001), color=edge[3])


def compute_louvain_communities(graph):
    community_map = {}
    if settings.COMMUNITIES != "LOUVAIN":
        return community_map, {}

    louvain_graph = graph.to_undirected()
    communities = nx.community.louvain_communities(louvain_graph, weight="weight", seed=0)
    communities = sorted(communities, key=len, reverse=True)
    for index, community in enumerate(communities, start=1):
        for node_id in community:
            community_map[node_id] = index

    return community_map, {}


def compute_kcore_communities(graph, k=10):
    community_map = {}
    if settings.COMMUNITIES != "KCORE":
        return community_map, {}

    core_graph = nx.k_core(graph.to_undirected(), k=k)
    core_nodes = set(core_graph.nodes())
    for node_id in graph.nodes():
        community_map[node_id] = 1 if node_id in core_nodes else 0

    return community_map, {}


def compute_infomap_communities(graph):
    community_map = {}
    if settings.COMMUNITIES != "INFOMAP":
        return community_map, {}

    infomap = Infomap("--two-level --directed")
    node_ids = sorted(graph.nodes())
    node_id_map = {node_id: index for index, node_id in enumerate(node_ids)}
    for source, target, edge_data in graph.edges(data=True):
        weight = edge_data.get("weight", 1.0)
        infomap.addLink(node_id_map[source], node_id_map[target], weight)

    infomap.run()
    module_ids = {}
    for node in infomap.nodes:
        original_id = node_ids[node.node_id]
        module_ids[original_id] = node.module_id

    if module_ids:
        module_map = {module_id: index for index, module_id in enumerate(sorted(set(module_ids.values())), start=1)}
        for node_id, module_id in module_ids.items():
            community_map[node_id] = module_map[module_id]

    return community_map, {}


def normalize_community_map(community_map):
    if not community_map:
        return {}
    community_counts = {}
    for community_id in community_map.values():
        community_counts[community_id] = community_counts.get(community_id, 0) + 1
    ordered = sorted(community_counts.items(), key=lambda item: (-item[1], item[0]))
    remap = {community_id: index for index, (community_id, _) in enumerate(ordered, start=1)}
    return {node_id: remap[community_id] for node_id, community_id in community_map.items()}


def build_community_palette(community_map):
    community_palette = {}
    if not community_map:
        return community_palette
    total = max(community_map.values())
    for index in range(1, total + 1):
        hue = (index - 1) / max(total, 1)
        r, g, b = colorsys.hsv_to_rgb(hue, 0.65, 0.9)
        community_palette[index] = (int(r * 255), int(g * 255), int(b * 255))
    return community_palette


def compute_communities(graph):
    if settings.COMMUNITIES == "LOUVAIN":
        community_map, _ = compute_louvain_communities(graph)
    elif settings.COMMUNITIES == "KCORE":
        community_map, _ = compute_kcore_communities(graph)
    elif settings.COMMUNITIES == "INFOMAP":
        community_map, _ = compute_infomap_communities(graph)
    else:
        return {}, {}
    community_map = normalize_community_map(community_map)
    return community_map, build_community_palette(community_map)


def apply_community_labels(graph, channel_dict, community_map):
    if settings.COMMUNITIES not in {"LOUVAIN", "KCORE", "INFOMAP"}:
        return
    for node_id, community_id in community_map.items():
        community_label = f"Community {community_id}"
        node_data = graph.nodes[node_id]["data"]
        node_data["group"] = community_label
        node_data["group_key"] = str(community_id)
        channel_dict[node_id]["data"]["group"] = community_label
        channel_dict[node_id]["data"]["group_key"] = str(community_id)


def apply_palette_colors(graph, channel_dict, edge_list, community_map, community_palette):
    palette_map = {}
    if settings.COMMUNITIES in {"LOUVAIN", "KCORE", "INFOMAP"}:
        for node_id, node_data in graph.nodes(data="data"):
            group_key = node_data.get("group_key")
            if not group_key:
                continue
            community_color = community_palette.get(int(group_key))
            if community_color:
                rgb_color = ",".join(str(value) for value in community_color)
                node_data["color"] = rgb_color
                channel_dict[node_id]["data"]["color"] = rgb_color
    else:
        if settings.COMMUNITIES_PALETTE == "ORGANIZATION":
            return palette_map
        group_keys = [
            str(org.key) for org in Organization.objects.filter(is_interesting=True).order_by("id").only("name")
        ]
        palette_map = colors_for_groups(sorted(set(group_keys)))
        for node_id, node_data in graph.nodes(data="data"):
            group_key = node_data.get("group_key")
            palette_color = palette_map.get(group_key) if palette_map else None
            if palette_color:
                node_data["color"] = palette_color
                channel_dict[node_id]["data"]["color"] = palette_color
    for edge in edge_list:
        source_color = channel_dict[edge[0]]["data"]["color"]
        target_color = channel_dict[edge[1]]["data"]["color"]
        color = rgb_avg(parse_color(source_color), parse_color(target_color))
        color = [str(int(c * 0.75)) for c in color]
        graph.edges[edge[0], edge[1]]["color"] = ",".join(color)
    return palette_map


def layout_positions(graph):
    forceatlas2 = ForceAtlas2(
        # Behavior alternatives
        outbound_attraction_distribution=True,  # Dissuade hubs
        edge_weight_influence=1.0,
        lin_log_mode=True,  # Use LinLog mode for attraction forces.
        # Performance
        jitter_tolerance=1.0,  # Tolerance
        barnes_hut_optimize=True,
        barnes_hut_theta=1.2,
        # Tuning
        scaling_ratio=2.0,
        strong_gravity_mode=False,
        gravity=1.0,
        # Log
        verbose=False,
    )
    return forceatlas2.forceatlas2_networkx_layout(graph, pos=None, iterations=settings.FA2_ITERATIONS)


def build_graph_data(graph, positions):
    data = {"nodes": [], "edges": []}
    for node_id, node_data in graph.nodes(data=True):
        node_info = {
            "id": node_id,
            "x": float(positions.get(node_data["data"]["pk"])[0]),
            "y": float(positions.get(node_data["data"]["pk"])[1]),
        }
        for key in (
            "label",
            "group",
            "group_key",
            "color",
            "pic",
            "url",
            "activity_period",
            "fans",
            "in_deg",
            "is_lost",
            "messages_count",
            "out_deg",
        ):
            node_info[key] = node_data["data"][key]
        data["nodes"].append(node_info)

    for index, (source, target, edge_data) in enumerate(graph.edges(data=True)):
        data["edges"].append(
            {
                "source": source,
                "target": target,
                "weight": edge_data.get("weight", 0),
                "color": edge_data.get("color", ""),
                "id": index,
            }
        )
    return data


def apply_node_measures(graph, data, channel_dict):
    for node in data["nodes"]:
        channel_entry = channel_dict.get(node["id"])
        if channel_entry is None:
            continue
        channel = channel_entry["channel"]
        node["in_deg"] = graph.in_degree(node["id"], weight="weight")
        node["out_deg"] = graph.out_degree(node["id"], weight="weight")
        node["fans"] = channel.participants_count
        node["messages_count"] = channel.message_set.count()
        node["label"] = channel.title
        node["activity_period"] = channel.activity_period


def apply_pagerank(graph, data, measures):
    key = "pagerank"
    measures.append((key, "PageRank"))
    pagerank_values = nx.pagerank(graph)
    for node in data["nodes"]:
        if node["id"] in pagerank_values:
            node[key] = pagerank_values[node["id"]]


def reposition_isolated_nodes(data, main_component):
    max_x = 0
    max_y = 0
    min_x = 0
    min_y = 0
    isolated = []
    for index, node in enumerate(data["nodes"]):
        if node["id"] in main_component:
            max_x = max(max_x, node["x"])
            max_y = max(max_y, node["y"])
            min_x = min(min_x, node["x"])
            min_y = min(min_y, node["y"])
        else:
            isolated.append(index)
    d = abs(max_x - min_x) / 200
    col = int(sqrt(len(isolated))) + 1
    for i in range(col):
        for j in range(col):
            index = i * col + j
            if len(isolated) > index:
                data["nodes"][isolated[index]]["x"] = max_x - i * d
                data["nodes"][isolated[index]]["y"] = max_y - j * d


def ensure_graph_root(root_target):
    try:
        shutil.rmtree(root_target)
        shutil.mkdir(root_target)
    except Exception:
        pass
    try:
        shutil.copytree("webapp_engine/map", root_target)
    except Exception:
        pass


def write_graph_files(data, accessory_payload, output_filename, accessory_filename):
    with open(output_filename, "w") as outputfile:
        outputfile.write(json.dumps(data))
    with open(accessory_filename, "w") as accessoryfile:
        accessoryfile.write(json.dumps(accessory_payload))


def build_group_payload(community_map, community_palette, palette_map, channel_dict):
    groups = []
    if settings.COMMUNITIES in {"LOUVAIN", "KCORE", "INFOMAP"} and community_map:
        community_counts = {}
        for community_id in community_map.values():
            community_counts[community_id] = community_counts.get(community_id, 0) + 1
        for community_id, count in community_counts.items():
            rgb = community_palette.get(community_id, DEFAULT_FALLBACK_COLOR)
            community_label = f"Community {community_id}"
            groups.append((str(community_id), count, community_label, rgb_to_hex(rgb)))
        groups = sorted(groups, key=lambda x: -x[1])
        main_groups = {str(community_id): f"Community {community_id}" for community_id in community_counts}
        return groups, main_groups

    org_qs = Organization.objects.filter(is_interesting=True)
    for organization in org_qs:
        if settings.COMMUNITIES_PALETTE != "ORGANIZATION":
            palette_color = palette_map.get(str(organization.key))
            color = rgb_to_hex(parse_color(palette_color)) if palette_color else organization.color
        else:
            color = organization.color
        groups.append((organization.id, organization.channel_set.count(), organization.name.replace(", ", ""), color))
    groups = sorted(groups, key=lambda x: -x[1])
    main_groups = {org.key: org.name for org in org_qs}
    return groups, main_groups


def copy_channel_media(root_target, qs):
    for channel in qs:
        try:
            if channel.username:
                shutil.copytree(
                    os.path.join(settings.MEDIA_ROOT, "channels", channel.username, "profile"),
                    os.path.join(root_target, "channels", channel.username, "profile"),
                )
        except Exception:
            pass


class Command(BaseCommand):
    args = ""
    help = "write file"

    def handle(self, *args, **options):
        print("Create graph")
        graph, channel_dict, qs = build_graph()
        edge_list = build_edge_list(channel_dict)

        if not edge_list:
            print("\n[ERROR] There are no relationships between channels, interrupting elaboration")
            exit()

        add_edges_to_graph(graph, edge_list)
        community_map, community_palette = compute_communities(graph)
        apply_community_labels(graph, channel_dict, community_map)
        palette_map = apply_palette_colors(graph, channel_dict, edge_list, community_map, community_palette)

        print("\nSet spatial distribution of nodes")
        positions = layout_positions(graph)

        print("\nCalculations on the graph")
        data = build_graph_data(graph, positions)

        print("- largest component")
        main_component = max(nx.weakly_connected_components(graph), key=len)

        print("- degrees, activity and fans")
        apply_node_measures(graph, data, channel_dict)

        measures = [
            ("in_deg", "Inbound connections"),
            ("out_deg", "Outbound connections"),
            ("fans", "Users"),
            ("messages_count", "Messages"),
        ]

        print("- pagerank")
        apply_pagerank(graph, data, measures)

        print("- small components")
        reposition_isolated_nodes(data, main_component)

        print("\nGenerate map")
        root_target = "graph"
        ensure_graph_root(root_target)

        print("- config files")
        output_filename = "graph/telegram_graph/data.json"
        groups, main_groups = build_group_payload(community_map, community_palette, palette_map, channel_dict)
        accessory_filename = "graph/telegram_graph/data_accessory.json"
        write_graph_files(
            data,
            {
                "main_groups": main_groups,
                "groups": groups,
                "measures": measures,
                "total_pages_count": qs.count(),
            },
            output_filename,
            accessory_filename,
        )

        print("- media")
        root_target = "graph/telegram_graph"
        copy_channel_media(root_target, qs)
