import datetime
import logging
from typing import Any

from django.conf import settings
from django.db.models import Count, Exists, F, Max, Min, OuterRef, Prefetch, Q, QuerySet

from network.utils import channel_cutoff_q, make_date_q
from webapp.models import Channel, ChannelAttribution, Message, ProfilePicture
from webapp.utils.channel_types import channel_type_filter
from webapp.utils.colors import hex_to_rgb

import networkx as nx

logger = logging.getLogger(__name__)


def channel_network_data(
    channel: Channel,
    default: dict | None = None,
    skip: frozenset[str] | set[str] = frozenset(),
    dead_leaves_color: str | None = None,
    resolved_org: "tuple[int, str, str] | None" = None,
) -> dict:
    """Build the graph-node dict for a channel.

    Node colour comes from the channel's *resolved* in-target organisation for
    the analysis window (``resolved_org`` = ``(id, name, color)``); channels
    with no in-target organisation in the window — *dead-leaf* nodes, i.e.
    out-of-target channels an in-target channel forwarded from or mentioned via
    a ``t.me/`` link — fall back to ``dead_leaves_color`` (or, when ``None``,
    ``settings.DEAD_LEAVES_COLOR``).
    """
    default = default or {}
    leaf_color = dead_leaves_color or settings.DEAD_LEAVES_COLOR
    org_color = resolved_org[2] if resolved_org else None
    data: dict = {
        "pk": str(channel.pk),
        "id": channel.telegram_id,
        "label": channel.title,
        "communities": {},
        "color": ",".join(map(str, hex_to_rgb(org_color or leaf_color))),
        "organization": resolved_org[1] if resolved_org else "",
        "resolved_org_id": resolved_org[0] if resolved_org else None,
        "resolved_org_color": org_color,
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


def _channel_activity_bounds(
    channel_pks: list[int],
) -> dict[int, tuple[datetime.date | None, datetime.date | None]]:
    """Per-channel (earliest, latest) message *date* over all stored messages."""
    bounds: dict[int, tuple[datetime.date | None, datetime.date | None]] = {}
    rows = (
        Message.objects.filter(channel_id__in=channel_pks)
        .exclude(date__isnull=True)
        .values("channel_id")
        .annotate(min_date=Min("date"), max_date=Max("date"))
    )
    for row in rows:
        mn, mx = row["min_date"], row["max_date"]
        bounds[row["channel_id"]] = (mn.date() if mn else None, mx.date() if mx else None)
    return bounds


def _in_target_period_tuples(
    channel: Channel,
) -> list[tuple[int, str, str, "datetime.date | None", "datetime.date | None"]]:
    """(org_id, org_name, org_color, start, end) for the channel's in-target periods.

    Reads from prefetched ``attributions__organization`` so it issues no query.
    """
    periods = []
    for attribution in channel.attributions.all():
        org = attribution.organization
        if org and org.is_in_target:
            periods.append((org.id, org.name, org.color, attribution.start, attribution.end))
    return periods


def resolve_window_organization(
    in_target_periods: list[tuple[int, str, str, "datetime.date | None", "datetime.date | None"]],
    window_start: datetime.date | None,
    window_end: datetime.date | None,
    channel_created: datetime.date | None,
    data_min: datetime.date | None,
    data_max: datetime.date | None,
) -> tuple[int, str, str] | None:
    """Pick the in-target org whose period covers the most days inside the window.

    Tiebreak: the period that starts earliest. ``None`` bounds are clamped — a
    period start falls back to channel creation / earliest activity / window
    start; a period end to the window end / latest activity / today; an open
    analysis window to the channel's data range. Returns ``(org_id, org_name,
    org_color)`` or ``None`` when no in-target period overlaps the window.
    """
    today = datetime.date.today()
    floor = channel_created or data_min or window_start or datetime.date.min
    w_lo = window_start or floor
    w_hi = window_end or data_max or today
    if w_hi < w_lo:
        w_hi = w_lo
    best_key: tuple[int, int] | None = None
    best_org: tuple[int, str, str] | None = None
    for org_id, org_name, org_color, p_start, p_end in in_target_periods:
        s = p_start or floor
        e = p_end or w_hi
        lo, hi = max(s, w_lo), min(e, w_hi)
        days = (hi - lo).days + 1 if hi >= lo else 0
        if days <= 0:
            continue
        key = (days, -s.toordinal())  # most days; tie -> earliest start
        if best_key is None or key > best_key:
            best_key, best_org = key, (org_id, org_name, org_color)
    return best_org


VALID_EDGE_WEIGHT_STRATEGIES = {"NONE", "TOTAL", "PARTIAL_MESSAGES", "PARTIAL_REFERENCES"}


def _filter_inactive_channels(
    channel_dict: dict[str, dict[str, Any]],
    graph: nx.DiGraph,
    channel_qs: QuerySet[Channel],
    messages_per_channel: dict,
) -> tuple[list[int], QuerySet[Channel]]:
    """Remove in-target channels with no activity in the date range from channel_dict and graph in-place.

    Dead-leaf nodes (out-of-target channels pulled in because an in-target channel
    cited them — identified by ``resolved_org_id is None``) are exempt: they have no
    in-target period, so the period-aware cutoff excludes all of their own messages
    and they would *always* be dropped here, before their incoming citation edges are
    even built. Their window relevance is whether they were cited *within* the window,
    which the degree-0 orphan sweep in ``build_graph`` decides once edges exist.
    """
    active_ids = set(messages_per_channel.keys())
    inactive = [
        cid
        for cid, cdata in channel_dict.items()
        if cdata["channel"].pk not in active_ids and cdata["data"].get("resolved_org_id") is not None
    ]
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
    for amplifier_pk, source_pk in set(forwarded_counts.keys()) | set(reference_counts.keys()):
        if not include_self_references and amplifier_pk == source_pk:
            continue
        f_count = forwarded_counts.get((amplifier_pk, source_pk), 0)
        m_count = reference_counts.get((amplifier_pk, source_pk), 0)
        total = f_count + m_count
        if edge_weight_strategy == "NONE":
            weight = 1.0
        elif edge_weight_strategy == "TOTAL":
            weight = float(total)
        elif edge_weight_strategy == "PARTIAL_MESSAGES":
            message_count = messages_per_channel.get(amplifier_pk, 0)
            weight = total / message_count if message_count else 0.0
        else:  # PARTIAL_REFERENCES (default)
            ref_count = referencing_counts.get(amplifier_pk, 0)
            weight = total / ref_count if ref_count else 0.0
        if weight > 0:
            # Citation orientation: a forward of source's content by amplifier
            # produces an amplifier→source edge, mirroring the citing→cited
            # convention of scientometric PageRank/HITS. Measures that need
            # the opposite content-flow orientation (SIR spreading, trophic
            # level) reverse the graph internally.
            edge: list[str | float] = [pk_to_str[amplifier_pk], pk_to_str[source_pk]]
            edge.extend([weight, float(f_count), float(m_count)])
            edge_list.append(edge)
    return edge_list


def build_graph(
    draw_dead_leaves: bool = False,
    start_date: datetime.date | None = None,
    end_date: datetime.date | None = None,
    channel_types: list[str] | None = None,
    channel_groups: list[str] | None = None,
    edge_weight_strategy: str = "PARTIAL_REFERENCES",
    include_mentions: bool = True,
    include_self_references: bool = False,
    include_lost: bool = False,
    include_private: bool = False,
    dead_leaves_color: str | None = None,
) -> tuple[nx.DiGraph, dict[str, dict[str, Any]], list[list[str | float]], QuerySet[Channel]]:
    """Build a directed NetworkX graph from channels in the DB.

    Returns (graph, channel_dict, edge_list, channel_qs).
    Raises ValueError if no edges are found between channels.

    A *dead-leaf* node is an out-of-target channel that at least one in-target
    channel has forwarded from or mentioned via a ``t.me/`` link. Inclusion is
    gated by ``draw_dead_leaves``: ``Channel.refresh_cited_degree()`` counts
    every such forward/mention from the in-target set and stores the total in
    ``in_degree``, so a non-zero in-degree is exactly the dead-leaf criterion.
    """
    # Node set: channels with an in-target period overlapping [start_date, end_date]
    # (the whole timeline when the window is open), plus dead leaves when requested.
    in_target_sub = ChannelAttribution.objects.filter(channel=OuterRef("pk"), organization__is_in_target=True)
    if end_date is not None:
        in_target_sub = in_target_sub.filter(Q(start__isnull=True) | Q(start__lte=end_date))
    if start_date is not None:
        in_target_sub = in_target_sub.filter(Q(end__isnull=True) | Q(end__gte=start_date))
    qs_filter = Q(Exists(in_target_sub))
    if draw_dead_leaves:
        # Dead-leaf criterion: an out-of-target channel cited (forwarded or
        # mentioned) at least once by some in-target channel. The cited count
        # lives in in_degree under the citation orientation (amplifier→source).
        qs_filter |= Q(in_degree__gt=0)
    channel_qs: QuerySet[Channel] = Channel.objects.filter(qs_filter, channel_type_filter(channel_types))
    if not include_private:
        channel_qs = channel_qs.exclude(is_private=True)
    if not include_lost:
        channel_qs = channel_qs.exclude(is_lost=True)
    channel_qs = channel_qs.prefetch_related(
        "attributions__organization",
        Prefetch(
            "profilepicture_set",
            queryset=ProfilePicture.objects.order_by("-date")[:1],
            to_attr="_prefetched_profile_pics",
        ),
    )
    if channel_groups:
        channel_qs = channel_qs.filter(groups__key__in=channel_groups).distinct()

    _skip = frozenset({"activity_period", "messages_count"})
    graph: nx.DiGraph = nx.DiGraph()
    channel_dict: dict[str, dict[str, Any]] = {}
    channels = list(channel_qs)
    activity_bounds = _channel_activity_bounds([channel.pk for channel in channels])
    for channel in channels:
        data_min, data_max = activity_bounds.get(channel.pk, (None, None))
        resolved_org = resolve_window_organization(
            _in_target_period_tuples(channel),
            start_date,
            end_date,
            channel.date.date() if channel.date else None,
            data_min,
            data_max,
        )
        node_data = channel_network_data(
            channel, skip=_skip, dead_leaves_color=dead_leaves_color, resolved_org=resolved_org
        )
        channel_dict[str(channel.pk)] = {"channel": channel, "data": node_data}
        graph.add_node(str(channel.pk), data=node_data)

    channel_ids = [int(channel_id) for channel_id in channel_dict]
    date_q = make_date_q(start_date, end_date)
    cutoff_q = channel_cutoff_q()
    references_through = Message.references.through

    messages_per_channel = {
        item["channel_id"]: item["total"]
        for item in Message.objects.alive()
        .filter(date_q, cutoff_q, channel_id__in=channel_ids)
        .values("channel_id")
        .annotate(total=Count("id"))
    }

    if start_date or end_date:
        channel_ids, channel_qs = _filter_inactive_channels(channel_dict, graph, channel_qs, messages_per_channel)

    forwarded_counts = {
        (item["channel_id"], item["forwarded_from_id"]): item["total"]
        for item in Message.objects.alive()
        .filter(date_q, cutoff_q, channel_id__in=channel_ids, forwarded_from_id__in=channel_ids)
        .values("channel_id", "forwarded_from_id")
        .annotate(total=Count("id"))
    }

    reference_counts = (
        {
            (item["message__channel_id"], item["channel_id"]): item["total"]
            for item in references_through.objects.filter(
                channel_cutoff_q("message__channel", "message__date"),
                make_date_q(start_date, end_date, field="message__date"),
                message__is_lost=False,
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
            for item in Message.objects.alive()
            .filter(date_q, cutoff_q, channel_id__in=channel_ids)
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
            # Un-rescaled tie weight (before the ×10/max normalisation): portable across
            # exports and used for the displayed In-/Out-strength node measures.
            weight_raw=float(edge[2]),
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
            if graph.degree(cid) == 0 and channel_dict[cid]["data"].get("resolved_org_id") is None
        ]
        for cid in orphaned:
            graph.remove_node(cid)
            del channel_dict[cid]
        channel_qs = channel_qs.filter(pk__in=[int(cid) for cid in channel_dict])

    return graph, channel_dict, edge_list, channel_qs
