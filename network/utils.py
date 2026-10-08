import datetime
from typing import TYPE_CHECKING, Any

from django.db.models import Exists, OuterRef, Q
from django.utils import timezone

import networkx as nx

if TYPE_CHECKING:
    from django.db.models import QuerySet

    from webapp.models import Channel

type GraphData = dict[str, list[dict[str, Any]]]
type CommunityTableData = dict[str, Any]
# CommunityTableData structure:
# {
#   "network_summary": dict,          # from _network_summary() plus "centralizations"
#   "strategies": {
#     strategy_key: [                 # ordered as in communities_data
#       {"group": tuple, "node_count": int, "metrics": dict},
#       ...
#     ]
#   },
#   "partition_comparison": {         # present when >= 2 comparable strategies (see community_stats)
#     "strategies": [strategy_key, ...],
#     "metrics": {"ari"|"ami"|"nmi"|"vi": [[float|None, ...], ...]},  # symmetric strategy×strategy
#   }
# }


def environment_channels(depth: int) -> "QuerySet[Channel]":
    """Channels reached by ``crawl_channels --environment`` within ``depth`` citation hops, minus the monitored ones.

    ``Channel.environment_depth`` is the distance the crawler stamped; a channel that also
    holds an in-target label over *any* period is a monitored channel and never counts as
    environment, whatever its stamp — in target always wins.
    """
    from webapp.models import Channel, ChannelLabel

    in_target = ChannelLabel.objects.filter(channel=OuterRef("pk"), label__is_in_target=True)
    return Channel.objects.filter(environment_depth__lte=depth).filter(~Exists(in_target))


def environment_window() -> "tuple[datetime.date | None, datetime.date | None] | None":
    """The environment window: the span of every in-target period, ``None`` when there is none.

    ``(earliest start, latest end)`` over all in-target ``ChannelLabel`` periods, inclusive;
    a side is ``None`` (open) when any period is open on it. One aggregate query. It is the
    window ``crawl_channels --environment`` stores environment messages for (there taken over
    the crawl scope's periods), and the bound :func:`channel_cutoff_q` puts on environment
    messages.
    """
    from django.db.models import Count, Max, Min

    from webapp.models import ChannelLabel

    agg = ChannelLabel.objects.filter(label__is_in_target=True).aggregate(
        periods=Count("pk"),
        earliest_start=Min("start"),
        latest_end=Max("end"),
        open_start=Count("pk", filter=Q(start__isnull=True)),
        open_end=Count("pk", filter=Q(end__isnull=True)),
    )
    if not agg["periods"]:
        return None
    start = None if agg["open_start"] else agg["earliest_start"]
    end = None if agg["open_end"] else agg["latest_end"]
    return start, end


def _local_midnight(day: datetime.date) -> datetime.datetime:
    """The first instant of ``day`` in the active time zone — the zone ``__date`` lookups bucket by."""
    return timezone.make_aware(datetime.datetime.combine(day, datetime.time.min))


def channel_cutoff_q(
    channel_field: str = "channel",
    date_field: str = "date",
    environment_depth: int | None = None,
) -> Q:
    """Q matching messages whose date falls inside one of their channel's in-target periods.

    A message is in-target iff its channel holds an in-target ``Label`` whose
    inclusive ``[start, end]`` membership interval (null bounds = open) contains
    the message date. Pass ``channel_field`` / ``date_field`` to adjust the ORM
    path when the Message is reached through a related model (e.g.
    ``message__channel`` / ``message__date`` for the references through-table).

    ``environment_depth`` widens the gate to the environment channels within that
    many citation hops (:func:`environment_channels`). They hold no in-target
    period of their own, so their messages count only inside the *environment
    window* (:func:`environment_window`): the span of every in-target period —
    from the earliest period start to the latest period end, inclusive local
    days, a side left open when any period is open on it, and no environment
    message at all when there is no in-target period. It is the window
    ``crawl_channels --environment`` stores environment messages for, re-applied
    here because a channel's stored history can reach past it (crawled in full
    while ``to_inspect``, or under a wider window in an earlier run). The window
    is read once, when the Q is built, and applied as local-midnight bounds on the
    raw datetime — the same days as the in-target branch's ``__date`` lookups,
    without a per-row date cast over the environment's messages, which typically
    far outnumber the in-target ones. ``None`` / ``0`` keeps the in-target-only gate.
    """
    from webapp.models import ChannelLabel

    subquery = (
        ChannelLabel.objects.filter(
            channel=OuterRef(channel_field),
            label__is_in_target=True,
        )
        .filter(Q(start__isnull=True) | Q(start__lte=OuterRef(f"{date_field}__date")))
        .filter(Q(end__isnull=True) | Q(end__gte=OuterRef(f"{date_field}__date")))
    )
    q = Q(Exists(subquery))
    if environment_depth:
        window = environment_window()
        if window is not None:
            start, end = window
            environment_q = Q(**{f"{channel_field}__in": environment_channels(environment_depth)})
            if start is not None:
                environment_q &= Q(**{f"{date_field}__gte": _local_midnight(start)})
            if end is not None:
                environment_q &= Q(**{f"{date_field}__lt": _local_midnight(end + datetime.timedelta(days=1))})
            q |= environment_q
    return q


def channel_period_date_q(channel: "Channel", date_field: str = "date") -> Q:
    """Q restricting messages to a single channel's in-target periods.

    Builds an OR-chain of inclusive date ranges over ``channel``'s in-target
    attribution periods — cheap (no correlated subquery), for single-channel
    call sites. Returns a match-nothing Q when the channel has no in-target
    period, so callers that want "show everything when unattributed" must guard
    with ``channel.in_target_periods.exists()``.
    """
    query = Q()
    has_period = False
    for start, end in channel.in_target_periods.values_list("start", "end"):
        has_period = True
        if start is None and end is None:
            # Fully-open period: every date qualifies. Return match-all now — folding
            # an empty Q() into the OR-chain would be absorbed (Q() | bounded == bounded),
            # silently dropping everything outside the other periods.
            return Q()
        interval = Q()
        if start is not None:
            interval &= Q(**{f"{date_field}__date__gte": start})
        if end is not None:
            interval &= Q(**{f"{date_field}__date__lte": end})
        query |= interval
    return query if has_period else Q(pk__in=[])


# Edge attribute ``build_graph`` stores the un-rescaled tie weight under (``weight`` is ×10/max per graph).
RAW_WEIGHT_KEY = "weight_raw"


def tie_weight_key(*graphs: nx.DiGraph) -> str:
    """Edge attribute holding the un-rescaled tie weight: ``weight_raw`` when every edge of every
    graph carries it (any ``build_graph`` output), else ``weight`` (hand-built graphs). Decided once
    across all *graphs* so the weights a caller compares are never a mix of the two scales."""
    for graph in graphs:
        if any(RAW_WEIGHT_KEY not in data for _, _, data in graph.edges(data=True)):
            return "weight"
    return RAW_WEIGHT_KEY


def to_undirected_sum(graph: nx.DiGraph, weight: str = "weight") -> nx.Graph:
    """Undirected projection of a DiGraph that **sums** reciprocal edge weights.

    ``DiGraph.to_undirected()`` keeps only one direction's weight when both
    ``(u, v)`` and ``(v, u)`` exist — the later-inserted edge silently overwrites
    the other — so a mutual tie loses half its weight, and *which* half survives
    depends on edge-insertion order. For weighted community detection and
    current-flow betweenness we want the total tie volume, i.e. the standard
    ``W + Wᵀ`` symmetrisation: ``w_undirected(u, v) = w(u, v) + w(v, u)``.

    Node attributes and isolated nodes are preserved; a self-loop keeps its single
    weight (there is only one direction to sum).
    """
    undirected = nx.Graph()
    undirected.add_nodes_from(graph.nodes(data=True))
    for u, v, data in graph.edges(data=True):
        w = data.get(weight, 1.0)
        if undirected.has_edge(u, v):
            undirected[u][v][weight] += w
        else:
            undirected.add_edge(u, v, **{**data, weight: w})
    return undirected


def make_date_q(
    start_date: datetime.date | None,
    end_date: datetime.date | None,
    field: str = "date",
) -> Q:
    """Build a Q filter for an inclusive date range on a DateTimeField.

    ``field`` is the ORM field name prefix (default ``"date"``), so the
    generated lookup is ``<field>__date__gte`` / ``<field>__date__lte``.
    Returns an empty Q() when both bounds are None.
    """
    q = Q()
    if start_date:
        q &= Q(**{f"{field}__date__gte": start_date})
    if end_date:
        q &= Q(**{f"{field}__date__lte": end_date})
    return q
