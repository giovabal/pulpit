import json
import logging
import os
import shutil
from math import sqrt
from typing import Any

from django.conf import settings
from django.db.models import QuerySet

from webapp.models import Channel

import networkx as nx

logger = logging.getLogger(__name__)

type GraphData = dict[str, list[dict[str, Any]]]


def build_graph_data(
    graph: nx.DiGraph,
    channel_dict: dict[str, Any],
    positions: dict[str, tuple[float, float]],
) -> GraphData:
    """Serialize graph nodes and edges into the output dict."""
    graph_data: GraphData = {"nodes": [], "edges": []}

    for node_id, node_data in graph.nodes(data=True):
        node_info: dict[str, Any] = {
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


def apply_base_node_measures(
    graph_data: GraphData, graph: nx.DiGraph, channel_dict: dict[str, Any]
) -> list[tuple[str, str]]:
    """Populate degree, fans, message count, and activity period on each node."""
    measures_labels: list[tuple[str, str]] = [
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


def apply_pagerank(graph_data: GraphData, graph: nx.DiGraph) -> list[tuple[str, str]]:
    """Add PageRank score to each node."""
    key = "pagerank"
    pagerank_values: dict[str, float] = nx.pagerank(graph)
    for node in graph_data["nodes"]:
        if node["id"] in pagerank_values:
            node[key] = pagerank_values[node["id"]]
    return [(key, "PageRank")]


def find_main_component(graph: nx.DiGraph) -> set[str]:
    return max(nx.weakly_connected_components(graph), key=len)


def reposition_isolated_nodes(graph_data: GraphData, main_component: set[str]) -> None:
    """Move isolated nodes (outside the main component) into a grid near the main cluster."""
    max_x = max_y = min_x = min_y = 0.0
    isolated_nodes: list[int] = []
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
            idx = i * col + j
            if len(isolated_nodes) > idx:
                graph_data["nodes"][isolated_nodes[idx]]["x"] = max_x - i * d
                graph_data["nodes"][isolated_nodes[idx]]["y"] = max_y - j * d


def ensure_graph_root(root_target: str) -> None:
    shutil.rmtree(root_target, ignore_errors=True)
    os.makedirs(root_target, exist_ok=True)
    try:
        shutil.copytree("webapp_engine/map", root_target, dirs_exist_ok=True)
    except OSError as e:
        logger.warning("Could not copy map template to %s: %s", root_target, e)


def write_graph_files(
    graph_data: GraphData,
    group_data: dict[str, Any],
    measures_labels: list[tuple[str, str]],
    channel_qs: QuerySet[Channel],
    output_filename: str,
    accessory_filename: str,
) -> None:
    with open(output_filename, "w") as outputfile:
        outputfile.write(json.dumps(graph_data))

    accessory_payload: dict[str, Any] = {
        "main_groups": group_data["main_groups"],
        "groups": group_data["groups"],
        "measures": measures_labels,
        "total_pages_count": channel_qs.count(),
    }
    with open(accessory_filename, "w") as accessoryfile:
        accessoryfile.write(json.dumps(accessory_payload))


def copy_channel_media(channel_qs: QuerySet[Channel], root_target: str) -> None:
    for channel in channel_qs:
        if not channel.username:
            continue
        src = os.path.join(settings.MEDIA_ROOT, "channels", channel.username, "profile")
        dst = os.path.join(root_target, "channels", channel.username, "profile")
        try:
            shutil.copytree(src, dst)
        except FileNotFoundError:
            pass
        except OSError as e:
            logger.warning("Could not copy media for channel %s: %s", channel.username, e)
