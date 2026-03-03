import logging

from django.conf import settings
from django.db.models import Count, Q

from webapp.models import Channel, Message

import networkx as nx

logger = logging.getLogger(__name__)


def build_graph(draw_dead_leaves=False):
    """Build a directed NetworkX graph from channels in the DB.

    Returns (graph, channel_dict, edge_list, channel_qs).
    Raises ValueError if no edges are found between channels.
    """
    qs_filter = Q(organization__is_interesting=True)
    if draw_dead_leaves:
        qs_filter |= Q(in_degree__gt=0)
    channel_qs = Channel.objects.filter(qs_filter)

    graph = nx.DiGraph()
    channel_dict = {}
    for channel in channel_qs:
        channel_dict[str(channel.pk)] = {"channel": channel, "data": channel.network_data()}
        graph.add_node(str(channel.pk), data=channel_dict[str(channel.pk)]["data"])

    channel_ids = [int(channel_id) for channel_id in channel_dict]

    messages_per_channel = {
        item["channel_id"]: item["total"]
        for item in Message.objects.filter(channel_id__in=channel_ids).values("channel_id").annotate(total=Count("id"))
    }

    forwarded_counts = {
        (item["channel_id"], item["forwarded_from_id"]): item["total"]
        for item in Message.objects.filter(channel_id__in=channel_ids, forwarded_from_id__in=channel_ids)
        .values("channel_id", "forwarded_from_id")
        .annotate(total=Count("id"))
    }

    references_through = Message.references.through
    reference_counts = {
        (item["message__channel_id"], item["channel_id"]): item["total"]
        for item in references_through.objects.filter(channel_id__in=channel_ids, message__channel_id__in=channel_ids)
        .values("message__channel_id", "channel_id")
        .annotate(total=Count("id"))
    }

    edge_list = []
    for source_id, source_data in channel_dict.items():
        for target_id, target_data in channel_dict.items():
            if source_id == target_id:
                continue
            source_pk = source_data["channel"].pk
            target_pk = target_data["channel"].pk
            message_count = messages_per_channel.get(target_pk, 0)
            forward_weight = forwarded_counts.get((target_pk, source_pk), 0)
            reference_weight = reference_counts.get((target_pk, source_pk), 0)
            weight = 0 if not message_count else (forward_weight + reference_weight) / message_count
            if weight > 0:
                edge = (
                    [str(target_data["channel"].pk), str(source_data["channel"].pk)]
                    if settings.REVERSED_EDGES
                    else [str(source_data["channel"].pk), str(target_data["channel"].pk)]
                )
                edge.append(weight)
                edge_list.append(edge)

    if not edge_list:
        raise ValueError("There are no relationships between channels.")

    max_weight = max(edge[2] for edge in edge_list)
    for edge in edge_list:
        graph.add_edge(edge[0], edge[1], weight=max(10 * edge[2] / max_weight, 0))

    return graph, channel_dict, edge_list, channel_qs
