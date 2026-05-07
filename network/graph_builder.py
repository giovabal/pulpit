import datetime
import logging
import math
from typing import Any

from django.conf import settings
from django.db.models import Count, Exists, F, OuterRef, Prefetch, Q, QuerySet

from network.utils import channel_cutoff_q, make_date_q
from webapp.models import Channel, Message, ProfilePicture
from webapp.utils.channel_types import channel_type_filter
from webapp.utils.colors import hex_to_rgb

import networkx as nx

logger = logging.getLogger(__name__)


def channel_network_data(
    channel: Channel,
    default: dict | None = None,
    skip: frozenset[str] | set[str] = frozenset(),
) -> dict:
    """Build the graph-node dict for a channel."""
    default = default or {}
    data: dict = {
        "pk": str(channel.pk),
        "id": channel.telegram_id,
        "label": channel.title,
        "communities": {},
        "color": ",".join(
            map(str, hex_to_rgb(channel.organization.color if channel.organization else settings.DEAD_LEAVES_COLOR))
        ),
        "pic": channel.profile_picture.picture.url[1:]
        if channel.profile_picture and channel.profile_picture.picture
        else "",
        "url": channel.telegram_url,
        "activity_period": "" if "activity_period" in skip else channel.activity_period,
        "fans": channel.participants_count,
        "in_deg": channel.in_degree,
        "is_lost": channel.is_lost,
        "is_private": channel.is_private,
        "messages_count": 0 if "messages_count" in skip else channel.message_set.count(),
        "out_deg": channel.out_degree,
    }
    data.update(default)
    return data


VALID_EDGE_WEIGHT_STRATEGIES = {"NONE", "TOTAL", "PARTIAL_MESSAGES", "PARTIAL_REFERENCES"}


def _recency_decay(date: datetime.datetime | datetime.date | None, today: datetime.date, n: int) -> float:
    """Return 1.0 for messages within the last N days, then exp(-(age-N)/N) beyond that."""
    if date is None or n <= 0:
        return 1.0
    d = date.date() if isinstance(date, datetime.datetime) else date
    excess = (today - d).days - n
    return math.exp(-excess / n) if excess > 0 else 1.0


def _filter_inactive_channels(
    channel_dict: dict[str, dict[str, Any]],
    graph: nx.DiGraph,
    channel_qs: QuerySet[Channel],
    messages_per_channel: dict,
) -> tuple[list[int], QuerySet[Channel]]:
    """Remove channels with no activity in the date range from channel_dict and graph in-place."""
    active_ids = set(messages_per_channel.keys())
    inactive = [cid for cid, cdata in channel_dict.items() if cdata["channel"].pk not in active_ids]
    for cid in inactive:
        graph.remove_node(cid)
        del channel_dict[cid]
    new_channel_ids = [int(cid) for cid in channel_dict]
    return new_channel_ids, channel_qs.filter(pk__in=new_channel_ids)


def _build_edge_list(
    forwarded_counts: dict,
    reference_counts: dict,
    referencing_counts: dict,
    messages_per_channel: dict,
    pk_to_str: dict[int, str],
    edge_weight_strategy: str,
    include_self_references: bool = False,
) -> list[list[str | float]]:
    """Compute weighted edge list from raw count dicts.

    Each row: [source, target, weight, weight_forwards, weight_mentions]
    weight_forwards and weight_mentions are the raw forward/mention counts
    (before any normalisation) available for CSV export.
    """
    edge_list: list[list[str | float]] = []
    for target_pk, source_pk in set(forwarded_counts.keys()) | set(reference_counts.keys()):
        if not include_self_references and target_pk == source_pk:
            continue
        f_count = forwarded_counts.get((target_pk, source_pk), 0)
        m_count = reference_counts.get((target_pk, source_pk), 0)
        total = f_count + m_count
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
            edge.extend([weight, float(f_count), float(m_count)])
            edge_list.append(edge)
    return edge_list


def build_graph(
    draw_dead_leaves: bool = False,
    start_date: datetime.date | None = None,
    end_date: datetime.date | None = None,
    recency_weights: int | None = None,
    channel_types: list[str] | None = None,
    channel_groups: list[str] | None = None,
    edge_weight_strategy: str = "PARTIAL_REFERENCES",
    include_mentions: bool = True,
    include_self_references: bool = False,
) -> tuple[nx.DiGraph, dict[str, dict[str, Any]], list[list[str | float]], QuerySet[Channel]]:
    """Build a directed NetworkX graph from channels in the DB.

    Returns (graph, channel_dict, edge_list, channel_qs).
    Raises ValueError if no edges are found between channels.
    """
    qs_filter = Q(organization__is_interesting=True)
    if draw_dead_leaves:
        # Citations are stored in in_degree when REVERSED_EDGES=True, out_degree otherwise.
        qs_filter |= Q(in_degree__gt=0) if settings.REVERSED_EDGES else Q(out_degree__gt=0)
    channel_qs: QuerySet[Channel] = (
        Channel.objects.filter(qs_filter, channel_type_filter(channel_types))
        .exclude(is_private=True)
        .select_related("organization")
        .prefetch_related(
            Prefetch(
                "profilepicture_set",
                queryset=ProfilePicture.objects.order_by("-date")[:1],
                to_attr="_prefetched_profile_pics",
            )
        )
    )
    if channel_groups:
        channel_qs = channel_qs.filter(groups__name__in=channel_groups).distinct()

    _skip = frozenset({"activity_period", "messages_count"})
    graph: nx.DiGraph = nx.DiGraph()
    channel_dict: dict[str, dict[str, Any]] = {}
    for channel in channel_qs:
        channel_dict[str(channel.pk)] = {"channel": channel, "data": channel_network_data(channel, skip=_skip)}
        graph.add_node(str(channel.pk), data=channel_dict[str(channel.pk)]["data"])

    channel_ids = [int(channel_id) for channel_id in channel_dict]
    date_q = make_date_q(start_date, end_date)
    cutoff_q = channel_cutoff_q()
    ref_cutoff_q = channel_cutoff_q("message__channel", "message__date")
    references_through = Message.references.through

    if recency_weights is not None:
        today = datetime.date.today()

        messages_per_channel: dict[int, float] = {}
        for ch_id, date in Message.objects.filter(date_q, cutoff_q, channel_id__in=channel_ids).values_list(
            "channel_id", "date"
        ):
            messages_per_channel[ch_id] = messages_per_channel.get(ch_id, 0.0) + _recency_decay(
                date, today, recency_weights
            )

        if start_date or end_date:
            channel_ids, channel_qs = _filter_inactive_channels(channel_dict, graph, channel_qs, messages_per_channel)

        forwarded_counts: dict[tuple[int, int], float] = {}
        for ch_id, fwd_id, date in Message.objects.filter(
            date_q, cutoff_q, channel_id__in=channel_ids, forwarded_from_id__in=channel_ids
        ).values_list("channel_id", "forwarded_from_id", "date"):
            key = (ch_id, fwd_id)
            forwarded_counts[key] = forwarded_counts.get(key, 0.0) + _recency_decay(date, today, recency_weights)

        reference_counts: dict[tuple[int, int], float] = {}
        if include_mentions:
            for src_ch_id, ref_ch_id, msg_date in (
                references_through.objects.filter(
                    make_date_q(start_date, end_date, field="message__date"),
                    ref_cutoff_q,
                    channel_id__in=channel_ids,
                    message__channel_id__in=channel_ids,
                )
                .exclude(message__forwarded_from=F("channel"))
                .values_list("message__channel_id", "channel_id", "message__date")
            ):
                key = (src_ch_id, ref_ch_id)
                reference_counts[key] = reference_counts.get(key, 0.0) + _recency_decay(
                    msg_date, today, recency_weights
                )

        referencing_counts: dict[int, float] = {}
        if edge_weight_strategy == "PARTIAL_REFERENCES":
            has_reference_subq = references_through.objects.filter(message=OuterRef("pk"))
            ref_filter = (
                Q(forwarded_from_id__isnull=False) | Q(Exists(has_reference_subq))
                if include_mentions
                else Q(forwarded_from_id__isnull=False)
            )
            for ch_id, date in (
                Message.objects.filter(date_q, cutoff_q, channel_id__in=channel_ids)
                .filter(ref_filter)
                .values_list("channel_id", "date")
            ):
                referencing_counts[ch_id] = referencing_counts.get(ch_id, 0.0) + _recency_decay(
                    date, today, recency_weights
                )

    else:
        messages_per_channel = {
            item["channel_id"]: item["total"]
            for item in Message.objects.filter(date_q, cutoff_q, channel_id__in=channel_ids)
            .values("channel_id")
            .annotate(total=Count("id"))
        }

        if start_date or end_date:
            channel_ids, channel_qs = _filter_inactive_channels(channel_dict, graph, channel_qs, messages_per_channel)

        forwarded_counts = {
            (item["channel_id"], item["forwarded_from_id"]): item["total"]
            for item in Message.objects.filter(
                date_q, cutoff_q, channel_id__in=channel_ids, forwarded_from_id__in=channel_ids
            )
            .values("channel_id", "forwarded_from_id")
            .annotate(total=Count("id"))
        }

        reference_counts = (
            {
                (item["message__channel_id"], item["channel_id"]): item["total"]
                for item in references_through.objects.filter(
                    make_date_q(start_date, end_date, field="message__date"),
                    channel_id__in=channel_ids,
                    message__channel_id__in=channel_ids,
                )
                .exclude(message__forwarded_from=F("channel"))
                .values("message__channel_id", "channel_id")
                .annotate(total=Count("id"))
            }
            if include_mentions
            else {}
        )

        referencing_counts = {}
        if edge_weight_strategy == "PARTIAL_REFERENCES":
            has_reference_subq = references_through.objects.filter(message=OuterRef("pk"))
            ref_filter = (
                Q(forwarded_from_id__isnull=False) | Q(Exists(has_reference_subq))
                if include_mentions
                else Q(forwarded_from_id__isnull=False)
            )
            referencing_counts = {
                item["channel_id"]: item["total"]
                for item in Message.objects.filter(date_q, cutoff_q, channel_id__in=channel_ids)
                .filter(ref_filter)
                .values("channel_id")
                .annotate(total=Count("id"))
            }

    pk_to_str: dict[int, str] = {data["channel"].pk: cid for cid, data in channel_dict.items()}
    edge_list = _build_edge_list(
        forwarded_counts,
        reference_counts,
        referencing_counts,
        messages_per_channel,
        pk_to_str,
        edge_weight_strategy,
        include_self_references=include_self_references,
    )

    if not edge_list:
        raise ValueError("There are no relationships between channels.")

    max_weight = max(edge[2] for edge in edge_list)
    for edge in edge_list:
        graph.add_edge(
            edge[0],
            edge[1],
            weight=10 * edge[2] / max_weight if max_weight else 0.0,
            weight_forwards=edge[3],
            weight_mentions=edge[4],
        )

    # Remove dead leaves that ended up with no edges after date filtering.
    # Their all-time DB degree earned them a slot, but the restricted window contains
    # no citations for them — they would otherwise appear as isolated ghost nodes.
    if draw_dead_leaves and (start_date or end_date):
        orphaned = [
            cid
            for cid in list(channel_dict)
            if graph.degree(cid) == 0
            and (
                channel_dict[cid]["channel"].organization is None
                or not channel_dict[cid]["channel"].organization.is_interesting
            )
        ]
        for cid in orphaned:
            graph.remove_node(cid)
            del channel_dict[cid]
        channel_qs = channel_qs.filter(pk__in=[int(cid) for cid in channel_dict])

    return graph, channel_dict, edge_list, channel_qs
