import json
import os
import shutil
from math import sqrt

from django.conf import settings
from django.core.management.base import BaseCommand

from webapp.models import Channel, Organization
from webapp_engine.utils import hex_to_rgb, rgb_avg

import networkx as nx
from fa2 import ForceAtlas2


class Command(BaseCommand):
    args = ""
    help = "write file"

    def handle(self, *args, **options):
        print("Create graph")
        graph = nx.DiGraph()
        channel_dict = {}
        qs = Channel.objects.filter(organization__is_interesting=True)
        for u in qs:
            channel_dict[str(u.telegram_id)] = u
            graph.add_node(str(u.pk), data=u.network_data)

        edge_list = []
        for u in qs:
            for v in qs.exclude(id=u.id):
                count = v.message_set.all().count()
                weight = (
                    0
                    if not count
                    else (
                        v.message_set.filter(forwarded_from=u).count()
                        + u.reference_message_set.filter(channel=v).count()
                    )
                    / count
                )
                if weight > 0:
                    color = rgb_avg(hex_to_rgb(u.organization.color), hex_to_rgb(v.organization.color))
                    color = [str(int(c * 0.75)) for c in color]
                    edge_list.append([str(v.pk), str(u.pk), weight, ",".join(color)])

        if not edge_list:
            print("\n[ERROR] There are no relationships between channels, interrupting elaboration")
            exit()

        max_weight = max([e[2] for e in edge_list])
        for edge in edge_list:
            graph.add_edge(edge[0], edge[1], weight=max(10 * edge[2] / max_weight, 0.0001), color=edge[3])

        print("\nSet spatial distribution of nodes")
        forceatlas2 = ForceAtlas2(
            # Behavior alternatives
            outboundAttractionDistribution=True,  # Dissuade hubs
            edgeWeightInfluence=1.0,
            # Performance
            jitterTolerance=1.0,  # Tolerance
            barnesHutOptimize=True,
            barnesHutTheta=1.2,
            # Tuning
            scalingRatio=2.0,
            strongGravityMode=False,
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
            ("in_deg", '"link" in ingresso'),
            ("out_deg", '"link" in uscita'),
            ("fans", "Numero di partecipanti"),
            ("messages_count", "Numero di messaggi"),
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

        accessory_filename = "graph/telegram_graph/data_accessory.json"
        with open(accessory_filename, "w") as accessoryfile:
            accessoryfile.write(
                json.dumps(
                    {
                        "main_groups": {org.key: org.name for org in org_qs},
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
