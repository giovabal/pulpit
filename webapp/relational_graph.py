import json
import os
import shutil
from math import sqrt

from django.conf import settings
from django.core.management.base import CommandError
from django.db.models import Q
from django.utils.text import slugify

from webapp.models import Channel, Organization
from webapp.utils import expand_colors, palette_colors, parse_color, rgb_avg, rgb_to_hex

import networkx as nx
from infomap import Infomap
from pyforceatlas2 import ForceAtlas2

DEFAULT_FALLBACK_COLOR = (204, 204, 204)
COMMUNITY_ALGORITHMS = {"LOUVAIN", "KCORE", "INFOMAP"}


class RelationalGraph:
    def __init__(self, communities_strategy, communities_palette, draw_dead_leaves=False):
        if communities_strategy not in COMMUNITY_ALGORITHMS and communities_strategy != "ORGANIZATION":
            raise CommandError(f"Communities identification strategy '{communities_strategy}' not found.")
        self.communities_strategy = communities_strategy

        try:
            palette_colors(communities_palette)
        except Exception as error:
            raise CommandError(f"Communities palette '{communities_palette}' not found.") from error
        self.communities_palette = communities_palette

        self.draw_dead_leaves = draw_dead_leaves

        qs_filter = Q(organization__is_interesting=True)
        if self.draw_dead_leaves:
            qs_filter |= Q(in_degree__gt=0)
        self.channel_qs = Channel.objects.filter(qs_filter)

        self.measures_labels = {}

        self.graph = nx.DiGraph()
        self.channel_dict = {}
        for channel in self.channel_qs:
            self.channel_dict[str(channel.pk)] = {"channel": channel, "data": channel.network_data()}
            self.graph.add_node(str(channel.pk), data=self.channel_dict[str(channel.pk)]["data"])

        self.edge_list = []
        for source_id, source_data in self.channel_dict.items():
            for target_id, target_data in self.channel_dict.items():
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
                    self.edge_list.append([str(target_data["channel"].pk), str(source_data["channel"].pk), weight])

        if not self.edge_list:
            print("\n[ERROR] There are no relationships between channels, interrupting elaboration")
            exit()

        max_weight = max(edge[2] for edge in self.edge_list)
        for edge in self.edge_list:
            self.graph.add_edge(edge[0], edge[1], weight=max(10 * edge[2] / max_weight, 0))

    def set_communities(self):
        self.communities, self.communities_palette = self.get_communities()
        self.apply_community_labels()

    def build_community_label(self, community_id):
        return slugify(f"{community_id}-{self.communities_strategy}")

    def apply_community_labels(self):
        for node_id, community_id in self.communities.items():
            detected_community = self.build_community_label(
                community_id
                if self.communities_strategy in COMMUNITY_ALGORITHMS
                else Organization.objects.get(pk=community_id).label
            )
            self.graph.nodes[node_id]["data"]["group"] = detected_community
            self.graph.nodes[node_id]["data"]["group_key"] = str(community_id)
            self.channel_dict[node_id]["data"]["group"] = detected_community
            self.channel_dict[node_id]["data"]["group_key"] = str(community_id)

    def apply_palette_colors(self):
        for node_id, node_data in self.graph.nodes(data="data"):
            group_key = node_data.get("group_key")
            community_color = None
            if group_key:
                community_color = self.communities_palette.get(int(group_key))
            if community_color is None:
                community_color = DEFAULT_FALLBACK_COLOR
            rgb_color = ",".join(str(value) for value in community_color)
            node_data["color"] = rgb_color
            self.channel_dict[node_id]["data"]["color"] = rgb_color

        for edge in self.edge_list:
            source_color = self.channel_dict[edge[0]]["data"]["color"]
            target_color = self.channel_dict[edge[1]]["data"]["color"]
            color = rgb_avg(parse_color(source_color), parse_color(target_color))
            color = [str(int(c * 0.75)) for c in color]
            self.graph.edges[edge[0], edge[1]]["color"] = ",".join(color)

    def get_communities(self):
        if self.communities_strategy == "LOUVAIN":
            community_map, community_palette = self.compute_louvain_communities()
        elif self.communities_strategy == "KCORE":
            community_map, community_palette = self.compute_kcore_communities()
        elif self.communities_strategy == "INFOMAP":
            community_map, community_palette = self.compute_infomap_communities()
        else:
            community_map, community_palette = self.compute_organization_communities()
        return self.normalize_community_map(community_map), community_palette

    def compute_louvain_communities(self):
        community_map = {}
        louvain_graph = self.graph.to_undirected()
        communities = nx.community.louvain_communities(louvain_graph, weight="weight", seed=0)
        communities = sorted(communities, key=len, reverse=True)
        for index, community in enumerate(communities, start=1):
            for node_id in community:
                community_map[node_id] = index

        return community_map, self.build_community_palette(community_map)

    def compute_organization_communities(self):
        community_map = {}
        community_palette = {}
        for channel_id, item in self.channel_dict.items():
            organization_id = item["channel"].organization_id
            community_map[channel_id] = item["channel"].organization_id
            community_palette[organization_id] = parse_color(item["channel"].organization.color)

        return community_map, community_palette

    def compute_kcore_communities(self, k=10):
        community_map = {}
        core_graph = nx.k_core(self.graph.to_undirected(), k=k)
        core_nodes = set(core_graph.nodes())
        for node_id in self.graph.nodes():
            community_map[node_id] = 1 if node_id in core_nodes else 0

        return community_map, self.build_community_palette(community_map)

    def compute_infomap_communities(self):
        community_map = {}
        infomap = Infomap("--two-level --directed")
        node_ids = sorted(self.graph.nodes())
        node_id_map = {node_id: index for index, node_id in enumerate(node_ids)}
        for source, target, edge_data in self.graph.edges(data=True):
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

        next_community = max(community_map.values(), default=0) + 1
        for node_id in node_ids:
            if node_id not in community_map:
                community_map[node_id] = next_community
                next_community += 1

        return community_map, self.build_community_palette(community_map)

    def normalize_community_map(self, community_map):
        community_counts = {}
        for community_id in community_map.values():
            community_counts[community_id] = community_counts.get(community_id, 0) + 1
        ordered = sorted(community_counts.items(), key=lambda item: (-item[1], item[0]))
        remap = {community_id: index for index, (community_id, _) in enumerate(ordered, start=1)}
        return {node_id: remap[community_id] for node_id, community_id in community_map.items()}

    def build_community_palette(self, community_map):
        if not community_map:
            return {}

        total = max(community_map.values())
        group_keys = [str(index) for index in range(1, total + 1)]
        palette_values = palette_colors(self.communities_palette)
        palette_values = expand_colors(palette_values, len(group_keys))
        palette_map = {
            group_key: ",".join(str(value) for value in parse_color(palette_color))
            for group_key, palette_color in zip(group_keys, palette_values, strict=False)
        }

        community_palette = {}
        for index in range(1, total + 1):
            palette_color = palette_map.get(str(index))
            community_palette[index] = parse_color(palette_color) if palette_color else DEFAULT_FALLBACK_COLOR
        return community_palette

    def set_layout_positions(self, iterations):
        self.positions = self.get_layout_positions(iterations)

    def get_layout_positions(self, iterations=10):
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
        return forceatlas2.forceatlas2_networkx_layout(self.graph, pos=None, iterations=iterations)

    def set_data(self):
        self.graph_data = {"nodes": [], "edges": []}
        for node_id, node_data in self.graph.nodes(data=True):
            node_info = {
                "id": node_id,
                "x": float(self.positions.get(node_data["data"]["pk"])[0]),
                "y": float(self.positions.get(node_data["data"]["pk"])[1]),
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
            self.graph_data["nodes"].append(node_info)

        for index, (source, target, edge_data) in enumerate(self.graph.edges(data=True)):
            self.graph_data["edges"].append(
                {
                    "source": source,
                    "target": target,
                    "weight": edge_data.get("weight", 0),
                    "color": edge_data.get("color", ""),
                    "id": index,
                }
            )

    def set_main_component(self):
        self.main_component = max(nx.weakly_connected_components(self.graph), key=len)

    def apply_base_node_measures(self):
        self.measures_labels.update(
            {
                "in_deg": "Inbound connections",
                "out_deg": "Outbound connections",
                "fans": "Users",
                "messages_count": "Messages",
            }
        )
        for node in self.graph_data["nodes"]:
            channel_entry = self.channel_dict.get(node["id"])
            if channel_entry is None:
                continue
            channel = channel_entry["channel"]
            node["in_deg"] = self.graph.in_degree(node["id"], weight="weight")
            node["out_deg"] = self.graph.out_degree(node["id"], weight="weight")
            node["fans"] = channel.participants_count
            node["messages_count"] = channel.message_set.count()
            node["label"] = channel.title
            node["activity_period"] = channel.activity_period

    def apply_pagerank(self):
        key = "pagerank"
        pagerank_values = nx.pagerank(self.graph)
        for node in self.graph_data["nodes"]:
            if node["id"] in pagerank_values:
                node[key] = pagerank_values[node["id"]]
        self.measures_labels.update({key: "PageRank"})

    def reposition_isolated_nodes(self):
        max_x = 0
        max_y = 0
        min_x = 0
        min_y = 0
        self.isolated_nodes = []
        for index, node in enumerate(self.graph_data["nodes"]):
            if node["id"] in self.main_component:
                max_x = max(max_x, node["x"])
                max_y = max(max_y, node["y"])
                min_x = min(min_x, node["x"])
                min_y = min(min_y, node["y"])
            else:
                self.isolated_nodes.append(index)
        d = abs(max_x - min_x) / 200
        col = int(sqrt(len(self.isolated_nodes))) + 1
        for i in range(col):
            for j in range(col):
                index = i * col + j
                if len(self.isolated_nodes) > index:
                    self.graph_data["nodes"][self.isolated_nodes[index]]["x"] = max_x - i * d
                    self.graph_data["nodes"][self.isolated_nodes[index]]["y"] = max_y - j * d

    def ensure_graph_root(self, root_target):
        try:
            shutil.rmtree(root_target)
            shutil.mkdir(root_target)
        except Exception:
            pass
        try:
            shutil.copytree("webapp_engine/map", root_target)
        except Exception:
            pass

    def write_graph_files(self, output_filename, accessory_filename):
        with open(output_filename, "w") as outputfile:
            outputfile.write(json.dumps(self.graph_data))

        accessory_payload = {
            "main_groups": self.group_data["main_groups"],
            "groups": self.group_data["groups"],
            "measures": self.measures_labels,
            "total_pages_count": self.channel_qs.count(),
        }
        with open(accessory_filename, "w") as accessoryfile:
            accessoryfile.write(json.dumps(accessory_payload))

    def build_group_payload(self):
        self.group_data = {"groups": []}
        if self.communities_strategy in COMMUNITY_ALGORITHMS:
            community_counts = {}
            for community_id in self.communities.values():
                community_counts[community_id] = community_counts.get(community_id, 0) + 1
            for community_id, count in community_counts.items():
                rgb = self.communities_palette.get(community_id, DEFAULT_FALLBACK_COLOR)
                detected_community = self.build_community_label(community_id)
                self.group_data["groups"].append((str(community_id), count, detected_community, rgb_to_hex(rgb)))
            self.group_data["main_groups"] = {
                str(community_id): self.build_community_label(community_id) for community_id in community_counts
            }
        else:
            org_qs = Organization.objects.filter(is_interesting=True)
            for organization in org_qs:
                self.group_data["groups"].append(
                    (
                        organization.id,
                        organization.channel_set.count(),
                        organization.name.replace(", ", ""),
                        organization.color,
                    )
                )
            self.group_data["main_groups"] = {org.key: org.name for org in org_qs}
        self.group_data["groups"] = sorted(self.group_data["groups"], key=lambda x: -x[1])

    def copy_channel_media(self, root_target):
        for channel in self.channel_qs:
            try:
                if channel.username:
                    shutil.copytree(
                        os.path.join(settings.MEDIA_ROOT, "channels", channel.username, "profile"),
                        os.path.join(root_target, "channels", channel.username, "profile"),
                    )
            except Exception:
                pass
