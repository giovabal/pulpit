import datetime
import logging
from typing import Any

from django.conf import settings
from django.db.models import Count, Exists, OuterRef, Prefetch, Q, QuerySet

from network.utils import make_date_q
from webapp.models import Channel, Message, ProfilePicture
from webapp.utils.channel_types import channel_type_filter

import networkx as nx

logger = logging.getLogger(__name__)

VALID_EDGE_WEIGHT_STRATEGIES = {"NONE", "TOTAL", "PARTIAL_MESSAGES", "PARTIAL_REFERENCES"}


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
    channel_qs: QuerySet[Channel] = (
        Channel.objects.filter(qs_filter, channel_type_filter())
        .select_related("organization")
        .prefetch_related(
            Prefetch(
                "profilepicture_set",
                queryset=ProfilePicture.objects.order_by("date"),
                to_attr="_prefetched_profile_pics",
            )
        )
    )

    _skip = frozenset({"activity_period", "messages_count"})
    graph: nx.DiGraph = nx.DiGraph()
    channel_dict: dict[str, dict[str, Any]] = {}
    for channel in channel_qs:
        channel_dict[str(channel.pk)] = {"channel": channel, "data": channel.network_data(skip=_skip)}
        graph.add_node(str(channel.pk), data=channel_dict[str(channel.pk)]["data"])

    channel_ids = [int(channel_id) for channel_id in channel_dict]
    date_q = make_date_q(start_date, end_date)

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
            make_date_q(start_date, end_date, field="message__date"),
            channel_id__in=channel_ids,
            message__channel_id__in=channel_ids,
        )
        .values("message__channel_id", "channel_id")
        .annotate(total=Count("id"))
    }

    edge_weight_strategy = settings.EDGE_WEIGHT_STRATEGY

    # For PARTIAL_REFERENCES: count messages per channel that are forwarded or contain citations.
    referencing_counts: dict[int, int] = {}
    if edge_weight_strategy == "PARTIAL_REFERENCES":
        has_reference_subq = references_through.objects.filter(message=OuterRef("pk"))
        referencing_counts = {
            item["channel_id"]: item["total"]
            for item in Message.objects.filter(date_q, channel_id__in=channel_ids)
            .filter(Q(forwarded_from_id__isnull=False) | Q(Exists(has_reference_subq)))
            .values("channel_id")
            .annotate(total=Count("id"))
        }

    pk_to_str: dict[int, str] = {data["channel"].pk: cid for cid, data in channel_dict.items()}
    edge_list: list[list[str | float]] = []
    for target_pk, source_pk in set(forwarded_counts.keys()) | set(reference_counts.keys()):
        if target_pk == source_pk:
            continue
        total = forwarded_counts.get((target_pk, source_pk), 0) + reference_counts.get((target_pk, source_pk), 0)
        if edge_weight_strategy == "NONE":
            weight = 1.0
        elif edge_weight_strategy == "TOTAL":
            weight = float(total)
        elif edge_weight_strategy == "PARTIAL_MESSAGES":
            message_count = messages_per_channel.get(target_pk, 0)
            weight = total / message_count if message_count else 0.0
        else:  # PARTIAL_REFERENCES (default)
            ref_count = referencing_counts.get(target_pk, 0)
            weight = total / ref_count if ref_count else 0.0
        if weight > 0:
            target_str = pk_to_str[target_pk]
            source_str = pk_to_str[source_pk]
            edge: list[str | float] = [target_str, source_str] if settings.REVERSED_EDGES else [source_str, target_str]
            edge.append(weight)
            edge_list.append(edge)

    if not edge_list:
        raise ValueError("There are no relationships between channels.")

    max_weight = max(edge[2] for edge in edge_list)
    for edge in edge_list:
        graph.add_edge(edge[0], edge[1], weight=10 * edge[2] / max_weight)

    return graph, channel_dict, edge_list, channel_qs
