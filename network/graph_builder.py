import datetime
import logging
from typing import Any

from django.conf import settings
from django.db.models import Count, Q, QuerySet

from webapp.models import Channel, Message
from webapp.utils.channel_types import channel_type_filter

import networkx as nx

logger = logging.getLogger(__name__)


def _make_date_q(
    start_date: datetime.date | None,
    end_date: datetime.date | None,
    field: str = "date",
) -> Q:
    q = Q()
    if start_date:
        q &= Q(**{f"{field}__date__gte": start_date})
    if end_date:
        q &= Q(**{f"{field}__date__lte": end_date})
    return q


def build_graph(
    draw_dead_leaves: bool = False,
    start_date: datetime.date | None = None,
    end_date: datetime.date | None = None,
) -> tuple[nx.DiGraph, dict[str, dict[str, Any]], list[list[str | float]], QuerySet[Channel]]:
    """Build a directed NetworkX graph from channels in the DB.

    Returns (graph, channel_dict, edge_list, channel_qs).
    Raises ValueError if no edges are found between channels.
    """
    qs_filter = Q(organization__is_interesting=True)
    if draw_dead_leaves:
        qs_filter |= Q(in_degree__gt=0)
    channel_qs: QuerySet[Channel] = Channel.objects.filter(qs_filter, channel_type_filter())

    graph: nx.DiGraph = nx.DiGraph()
    channel_dict: dict[str, dict[str, Any]] = {}
    for channel in channel_qs:
        channel_dict[str(channel.pk)] = {"channel": channel, "data": channel.network_data()}
        graph.add_node(str(channel.pk), data=channel_dict[str(channel.pk)]["data"])

    channel_ids = [int(channel_id) for channel_id in channel_dict]
    date_q = _make_date_q(start_date, end_date)

    messages_per_channel: dict[int, int] = {
        item["channel_id"]: item["total"]
        for item in Message.objects.filter(date_q, channel_id__in=channel_ids)
        .values("channel_id")
        .annotate(total=Count("id"))
    }

    if start_date or end_date:
        active_ids = set(messages_per_channel.keys())
        inactive = [cid for cid, cdata in channel_dict.items() if cdata["channel"].pk not in active_ids]
        for cid in inactive:
            graph.remove_node(cid)
            del channel_dict[cid]
        channel_ids = [int(cid) for cid in channel_dict]
        channel_qs = channel_qs.filter(pk__in=channel_ids)

    forwarded_counts: dict[tuple[int, int], int] = {
        (item["channel_id"], item["forwarded_from_id"]): item["total"]
        for item in Message.objects.filter(date_q, channel_id__in=channel_ids, forwarded_from_id__in=channel_ids)
        .values("channel_id", "forwarded_from_id")
        .annotate(total=Count("id"))
    }

    references_through = Message.references.through
    reference_counts: dict[tuple[int, int], int] = {
        (item["message__channel_id"], item["channel_id"]): item["total"]
        for item in references_through.objects.filter(
            _make_date_q(start_date, end_date, field="message__date"),
            channel_id__in=channel_ids,
            message__channel_id__in=channel_ids,
        )
        .values("message__channel_id", "channel_id")
        .annotate(total=Count("id"))
    }

    edge_list: list[list[str | float]] = []
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
                edge: list[str | float] = (
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
        graph.add_edge(edge[0], edge[1], weight=10 * edge[2] / max_weight)

    return graph, channel_dict, edge_list, channel_qs
