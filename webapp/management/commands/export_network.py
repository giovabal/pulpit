import colorsys
import json
import os
import shutil
from math import sqrt

from django.conf import settings
from django.core.management.base import BaseCommand
from django.db.models import Q

from webapp.models import Channel, Organization
from webapp_engine.utils import hex_to_rgb, rgb_avg

import networkx as nx
from fa2 import ForceAtlas2


class Command(BaseCommand):
    args = ""
    help = "write file"

    def handle(self, *args, **options):
        def parse_color(value):
            if isinstance(value, str) and "," in value:
                return tuple(int(part.strip()) for part in value.split(","))
            return hex_to_rgb(value)

        print("Create graph")
        graph = nx.DiGraph()
        channel_dict = {}
        qs_filter = Q(organization__is_interesting=True)
        if settings.DRAW_DEAD_LEAVES:
            qs_filter |= Q(in_degree__gt=0)
        qs = Channel.objects.filter(qs_filter)
        for u in qs:
            channel_dict[str(u.pk)] = {"channel": u, "data": u.network_data()}
            graph.add_node(str(u.pk), data=channel_dict[str(u.pk)]["data"])

        edge_list = []
        for k, u in channel_dict.items():
            for j, v in channel_dict.items():
                if k == j:
                    continue
                count = v["channel"].message_set.all().count()
                weight = (
                    0
                    if not count
                    else (
                        v["channel"].message_set.filter(forwarded_from=u["channel"]).count()
                        + u["channel"].reference_message_set.filter(channel=v["channel"]).count()
                    )
                    / count
                )
                if weight > 0:
                    color = rgb_avg(
                        parse_color(u["data"]["color"] if u["channel"].organization else settings.DEAD_LEAVES_COLOR),
                        parse_color(v["data"]["color"] if v["channel"].organization else settings.DEAD_LEAVES_COLOR),
                    )
                    color = [str(int(c * 0.75)) for c in color]
                    edge_list.append([str(v["channel"].pk), str(u["channel"].pk), weight, ",".join(color)])

        if not edge_list:
            print("\n[ERROR] There are no relationships between channels, interrupting elaboration")
            exit()

        max_weight = max([e[2] for e in edge_list])
        for edge in edge_list:
            graph.add_edge(edge[0], edge[1], weight=max(10 * edge[2] / max_weight, 0.0001), color=edge[3])

        community_map = {}
        community_palette = {}
        if settings.COMMUNITIES == "LOUVAIN" or settings.COMMUNITIES_PALETTE == "LOUVAIN":
            louvain_graph = graph.to_undirected()
            communities = nx.community.louvain_communities(louvain_graph, weight="weight", seed=0)
            communities = sorted(communities, key=len, reverse=True)
            for index, community in enumerate(communities, start=1):
                for node_id in community:
                    community_map[node_id] = index

            if community_map:
                total = max(community_map.values())
                for index in range(1, total + 1):
                    hue = (index - 1) / max(total, 1)
                    r, g, b = colorsys.hsv_to_rgb(hue, 0.65, 0.9)
                    community_palette[index] = (int(r * 255), int(g * 255), int(b * 255))

        if settings.COMMUNITIES == "LOUVAIN":
            for node_id, community_id in community_map.items():
                community_label = f"Community {community_id}"
                node_data = graph.nodes[node_id]["data"]
                node_data["group"] = community_label
                node_data["group_key"] = str(community_id)
                channel_dict[node_id]["data"]["group"] = community_label
                channel_dict[node_id]["data"]["group_key"] = str(community_id)

        if settings.COMMUNITIES_PALETTE == "LOUVAIN":
            for node_id, community_id in community_map.items():
                rgb = community_palette.get(community_id)
                if not rgb:
                    continue
                rgb_string = ",".join(str(value) for value in rgb)
                node_data = graph.nodes[node_id]["data"]
                node_data["color"] = rgb_string
                channel_dict[node_id]["data"]["color"] = rgb_string
            for edge in edge_list:
                source_color = channel_dict[edge[0]]["data"]["color"]
                target_color = channel_dict[edge[1]]["data"]["color"]
                color = rgb_avg(parse_color(source_color), parse_color(target_color))
                color = [str(int(c * 0.75)) for c in color]
                graph.edges[edge[0], edge[1]]["color"] = ",".join(color)

        print("\nSet spatial distribution of nodes")
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

        positions = forceatlas2.forceatlas2_networkx_layout(graph, pos=None, iterations=settings.FA2_ITERATIONS)

        print("\nCalculations on the graph")
        data = {"nodes": [], "edges": []}
        for u, d in graph.nodes(data=True):
            node_info = {
                "id": u,
                "x": float(positions.get(d["data"]["pk"])[0]),
                "y": float(positions.get(d["data"]["pk"])[1]),
            }
            for k in (
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
                node_info[k] = d["data"][k]
            data["nodes"].append(node_info)

        i = 0
        for u, v, d in graph.edges(data=True):
            data["edges"].append(
                {"source": u, "target": v, "weight": d.get("weight", 0), "color": d.get("color", ""), "id": i}
            )
            i += 1

        properties = {}
        graph_properties = []

        print("- nodes and edges count")
        key = "nodes-count"
        graph_properties.append((key, "Nodes count"))
        properties[key] = graph.number_of_nodes()
        key = "edges-count"
        graph_properties.append((key, "Edge count"))
        properties[key] = graph.number_of_edges()

        print("- largest component")
        main_component = max(nx.weakly_connected_components(graph), key=len)

        print("- degrees, activity and fans")
        for node in data["nodes"]:
            channel = channel_dict.get(node["id"])
            if channel is None:
                continue
            node["in_deg"] = graph.in_degree(node["id"], weight="weight")
            node["out_deg"] = graph.out_degree(node["id"], weight="weight")
            node["fans"] = channel.participants_count
            node["messages_count"] = channel.message_set.count()
            node["label"] = channel.title
            node["activity_period"] = channel.activity_period

        measures = [
            ("in_deg", "Inbound connections"),
            ("out_deg", "Outbound connections"),
            ("fans", "Users"),
            ("messages_count", "Messages"),
        ]

        print("- pagerank")
        k = "pagerank"
        measures.append((k, "PageRank"))
        vp = nx.pagerank(graph)
        for node in data["nodes"]:
            try:
                node[k] = vp[node["id"]]
            except KeyError:
                continue

        print("- small components")
        max_x = 0
        max_y = 0
        min_x = 0
        min_y = 0
        isolated = []
        for i, node in enumerate(data["nodes"]):
            if node["id"] in main_component:
                max_x = max(max_x, node["x"])
                max_y = max(max_y, node["y"])
                min_x = min(min_x, node["x"])
                min_y = min(min_y, node["y"])
            else:
                isolated.append(i)
        d = abs(max_x - min_x) / 200
        col = int(sqrt(len(isolated))) + 1
        for i in range(col):
            for j in range(col):
                index = i * col + j
                if len(isolated) > index:
                    data["nodes"][isolated[index]]["x"] = max_x - i * d
                    data["nodes"][isolated[index]]["y"] = max_y - j * d

        print("\nGenerate map")
        root_target = "graph"
        try:
            shutil.rmtree(root_target)
            shutil.mkdir(root_target)
        except Exception:
            pass

        try:
            shutil.copytree("webapp_engine/map", root_target)
        except Exception:
            pass

        print("- config files")
        output_filename = "graph/telegram_graph/data.json"
        with open(output_filename, "w") as outputfile:
            outputfile.write(json.dumps(data))

        groups = []
        if settings.COMMUNITIES == "LOUVAIN" and community_map:
            community_counts = {}
            for community_id in community_map.values():
                community_counts[community_id] = community_counts.get(community_id, 0) + 1
            for community_id, count in community_counts.items():
                rgb = community_palette.get(community_id, (204, 204, 204))
                groups.append(
                    (
                        str(community_id),
                        count,
                        f"Community {community_id}",
                        f"#{rgb[0]:02x}{rgb[1]:02x}{rgb[2]:02x}",
                    )
                )
            groups = sorted(groups, key=lambda x: -x[1])
            main_groups = {str(community_id): f"Community {community_id}" for community_id in community_counts}
        else:
            org_qs = Organization.objects.filter(is_interesting=True)
            for organization in org_qs:
                groups.append(
                    (
                        organization.id,
                        organization.channel_set.count(),
                        organization.name.replace(", ", ""),
                        organization.color,
                    )
                )
            groups = sorted(groups, key=lambda x: -x[1])
            main_groups = {org.key: org.name for org in org_qs}

        accessory_filename = "graph/telegram_graph/data_accessory.json"
        with open(accessory_filename, "w") as accessoryfile:
            accessoryfile.write(
                json.dumps(
                    {
                        "main_groups": main_groups,
                        "groups": groups,
                        "measures": measures,
                        "total_pages_count": qs.count(),
                    }
                )
            )

        print("- media")
        root_target = "graph/telegram_graph"
        for channel in qs:
            try:
                if channel.username:
                    shutil.copytree(
                        os.path.join(settings.MEDIA_ROOT, "channels", channel.username, "profile"),
                        os.path.join(root_target, "channels", channel.username, "profile"),
                    )
            except Exception:
                pass
