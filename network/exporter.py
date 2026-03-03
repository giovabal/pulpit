import json
import os
import shutil
from math import sqrt

from django.conf import settings

import networkx as nx


def build_graph_data(graph, channel_dict, positions):
    """Serialize graph nodes and edges into the output dict."""
    graph_data = {"nodes": [], "edges": []}

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
        graph_data["nodes"].append(node_info)

    for index, (source, target, edge_data) in enumerate(graph.edges(data=True)):
        graph_data["edges"].append(
            {
                "source": source,
                "target": target,
                "weight": edge_data.get("weight", 0),
                "color": edge_data.get("color", ""),
                "id": index,
            }
        )

    return graph_data


def apply_base_node_measures(graph_data, graph, channel_dict):
    """Populate degree, fans, message count, and activity period on each node."""
    measures_labels = [
        ("in_deg", "Inbound connections"),
        ("out_deg", "Outbound connections"),
        ("fans", "Users"),
        ("messages_count", "Messages"),
    ]
    for node in graph_data["nodes"]:
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
    return measures_labels


def apply_pagerank(graph_data, graph):
    """Add PageRank score to each node."""
    key = "pagerank"
    pagerank_values = nx.pagerank(graph)
    for node in graph_data["nodes"]:
        if node["id"] in pagerank_values:
            node[key] = pagerank_values[node["id"]]
    return [(key, "PageRank")]


def find_main_component(graph):
    return max(nx.weakly_connected_components(graph), key=len)


def reposition_isolated_nodes(graph_data, main_component):
    """Move isolated nodes (outside the main component) into a grid near the main cluster."""
    max_x = max_y = min_x = min_y = 0
    isolated_nodes = []
    for index, node in enumerate(graph_data["nodes"]):
        if node["id"] in main_component:
            max_x = max(max_x, node["x"])
            max_y = max(max_y, node["y"])
            min_x = min(min_x, node["x"])
            min_y = min(min_y, node["y"])
        else:
            isolated_nodes.append(index)
    d = abs(max_x - min_x) / 200
    col = int(sqrt(len(isolated_nodes))) + 1
    for i in range(col):
        for j in range(col):
            index = i * col + j
            if len(isolated_nodes) > index:
                graph_data["nodes"][isolated_nodes[index]]["x"] = max_x - i * d
                graph_data["nodes"][isolated_nodes[index]]["y"] = max_y - j * d


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


def write_graph_files(graph_data, group_data, measures_labels, channel_qs, output_filename, accessory_filename):
    with open(output_filename, "w") as outputfile:
        outputfile.write(json.dumps(graph_data))

    accessory_payload = {
        "main_groups": group_data["main_groups"],
        "groups": group_data["groups"],
        "measures": measures_labels,
        "total_pages_count": channel_qs.count(),
    }
    with open(accessory_filename, "w") as accessoryfile:
        accessoryfile.write(json.dumps(accessory_payload))


def copy_channel_media(channel_qs, root_target):
    for channel in channel_qs:
        try:
            if channel.username:
                shutil.copytree(
                    os.path.join(settings.MEDIA_ROOT, "channels", channel.username, "profile"),
                    os.path.join(root_target, "channels", channel.username, "profile"),
                )
        except Exception:
            pass
