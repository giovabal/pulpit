import datetime
from typing import TYPE_CHECKING, Any

from django.db.models import Exists, OuterRef, Q

import networkx as nx

if TYPE_CHECKING:
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


def channel_cutoff_q(channel_field: str = "channel", date_field: str = "date") -> Q:
    """Q matching messages whose date falls inside one of their channel's in-target periods.

    A message is in-target iff its channel holds an in-target ``Label`` whose
    inclusive ``[start, end]`` membership interval (null bounds = open) contains
    the message date. Pass ``channel_field`` / ``date_field`` to adjust the ORM
    path when the Message is reached through a related model (e.g.
    ``message__channel`` / ``message__date`` for the references through-table).
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
    return Q(Exists(subquery))


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
