import datetime
import logging
from typing import Any

from django.db.models import Count, Q

from network.utils import GraphData, channel_cutoff_q, make_date_q
from webapp.models import Message

import networkx as nx

logger = logging.getLogger(__name__)


def apply_amplification_factor(
    graph_data: GraphData,
    graph: nx.DiGraph,
    channel_dict: dict[str, Any],
    start_date: datetime.date | None = None,
    end_date: datetime.date | None = None,
) -> list[tuple[str, str]]:
    """Add amplification factor (forwards received / own message count) to each node."""
    key = "amplification_factor"

    channel_pks = [
        channel_dict[node["id"]]["channel"].pk for node in graph_data["nodes"] if channel_dict.get(node["id"])
    ]
    msg_q = Q(channel_id__in=channel_pks) & make_date_q(start_date, end_date) & channel_cutoff_q()
    message_counts: dict[int, int] = {
        item["channel_id"]: item["total"]
        for item in Message.objects.filter(msg_q).values("channel_id").annotate(total=Count("id"))
    }

    fwd_q = (
        Q(forwarded_from_id__in=channel_pks, channel_id__in=channel_pks)
        & make_date_q(start_date, end_date)
        & channel_cutoff_q()
    )
    forwards_received: dict[int, int] = {
        item["forwarded_from_id"]: item["total"]
        for item in Message.objects.filter(fwd_q).values("forwarded_from_id").annotate(total=Count("id"))
    }

    for node in graph_data["nodes"]:
        channel_entry = channel_dict.get(node["id"])
        if channel_entry is None:
            continue
        pk = channel_entry["channel"].pk
        mc = message_counts.get(pk, 0)
        fr = forwards_received.get(pk, 0)
        node[key] = round(fr / mc, 4) if mc > 0 else 0.0

    return [(key, "Amplification Factor")]


def apply_content_originality(
    graph_data: GraphData,
    graph: nx.DiGraph,
    channel_dict: dict[str, Any],
    start_date: datetime.date | None = None,
    end_date: datetime.date | None = None,
) -> list[tuple[str, str]]:
    """Add content originality (1 − forwarded_messages / total_messages) to each node. None if no messages."""
    key = "content_originality"

    channel_pks = [
        channel_dict[node["id"]]["channel"].pk for node in graph_data["nodes"] if channel_dict.get(node["id"])
    ]
    msg_q = Q(channel_id__in=channel_pks) & make_date_q(start_date, end_date) & channel_cutoff_q()
    message_counts: dict[int, int] = {
        item["channel_id"]: item["total"]
        for item in Message.objects.filter(msg_q).values("channel_id").annotate(total=Count("id"))
    }
    fwd_q = msg_q & Q(forwarded_from__isnull=False)
    forwarded_counts: dict[int, int] = {
        item["channel_id"]: item["total"]
        for item in Message.objects.filter(fwd_q).values("channel_id").annotate(total=Count("id"))
    }

    for node in graph_data["nodes"]:
        channel_entry = channel_dict.get(node["id"])
        if channel_entry is None:
            continue
        pk = channel_entry["channel"].pk
        mc = message_counts.get(pk, 0)
        node[key] = round(1 - forwarded_counts.get(pk, 0) / mc, 4) if mc > 0 else None

    return [(key, "Content Originality")]
