"""Temporal co-forwarding coordination analysis.

Two channels form a *coordination tie* when they repeatedly forward the **same
origin message** within a short time window of each other. This is a second
network layer, deliberately distinct from the citation graph: the citation
graph records *who amplifies whom*; the coordination graph records *who moves
in step with whom*. Because every event is a dyadic fact carrying its own
timestamp (channel X forwarded origin message M at time t), the layer is fully
consistent with Pulpit's one-degree attribution model — no path or flow claim
is involved.

Method lineage: coordinated link-sharing behaviour (Giglietto, Righetti, Rossi
& Marino 2020), coordination-network detection from action traces (Pacheco,
Hui, Torres-Lugo, Truong, Flammini & Menczer 2021; Nizzoli, Tardelli, Avvenuti,
Cresci & Tesconi 2021), and the synchronized-action framework (Magelinski, Ng &
Carley 2022). The repetition threshold (``min_events`` distinct shared origins
per pair) is what separates arrangement from coincidence on viral content —
one shared burst is news, many shared bursts are behaviour.

Origin identity: Telegram attributes every forward to the original author, so
a forward row identifies its origin message as ``(forwarded_from,
fwd_from_channel_post)``; rows missing the post id fall back to
``(forwarded_from, fwd_from_date)`` (channel + original timestamp), and rows
carrying neither are skipped. Per channel and origin only the *earliest*
forward counts — re-shares of the same origin by the same channel are not
extra events.
"""

import datetime
from collections import Counter
from collections.abc import Iterable, Iterator
from dataclasses import dataclass

from django.db.models import F, Q

from network.utils import channel_cutoff_q, make_date_q
from webapp.models import Message

import networkx as nx

DEFAULT_WINDOW_SECONDS = 300
DEFAULT_MIN_EVENTS = 3

# Coordination-specific node measures, in the order the map's "Nodes dimension"
# selector should offer them (the first entry is the default size key).
COORDINATION_MEASURES: list[tuple[str, str]] = [
    ("coordination_strength", "Coordinated co-forwards"),
    ("coordination_partners", "Coordination partners"),
    ("coordination_ratio", "Coordinated-forward share"),
]

# Context columns copied verbatim from the main graph's base measures, so the
# coordination map's info panel and size selector keep the familiar volume keys.
_CONTEXT_MEASURES: list[tuple[str, str]] = [
    ("in_deg", "In-strength"),
    ("out_deg", "Out-strength"),
    ("fans", "Users"),
    ("messages_count", "Messages"),
]


def coordination_measures_labels() -> list[tuple[str, str]]:
    """(key, label) pairs for the coordination map's ``channels.json``."""
    return COORDINATION_MEASURES + _CONTEXT_MEASURES


@dataclass(frozen=True)
class CoordinationResult:
    """Outcome of :func:`compute_coordination`.

    ``edges`` holds one entry per retained (unordered) channel pair — node ids
    are the graph convention ``str(channel.pk)``, ``a < b`` numerically — with
    the number of distinct origin messages the pair co-forwarded inside the
    window. ``node_scores`` covers exactly the channels appearing in ``edges``.
    """

    edges: list[tuple[str, str, int]]
    node_scores: dict[str, dict[str, float]]
    channels_seen: int
    origins_seen: int
    window_seconds: int
    min_events: int

    @property
    def node_ids(self) -> list[str]:
        ids = {a for a, _b, _n in self.edges} | {b for _a, b, _n in self.edges}
        return sorted(ids, key=int)


def _window_pairs(
    entries: list[tuple[datetime.datetime, int]],
    window: datetime.timedelta,
) -> Iterator[tuple[int, int]]:
    """Unordered channel pairs whose forward times lie within ``window`` of each other.

    ``entries`` is one origin message's ``(first_forward_time, channel_id)``
    list, sorted by time; each channel appears at most once, so every yielded
    pair is a distinct co-forwarding event for that origin.
    """
    for i in range(len(entries) - 1):
        t_i, ch_i = entries[i]
        for j in range(i + 1, len(entries)):
            t_j, ch_j = entries[j]
            if t_j - t_i > window:
                break
            yield (ch_i, ch_j) if ch_i < ch_j else (ch_j, ch_i)


def compute_coordination(
    channel_ids: Iterable[int],
    *,
    start_date: datetime.date | None = None,
    end_date: datetime.date | None = None,
    window_seconds: int = DEFAULT_WINDOW_SECONDS,
    min_events: int = DEFAULT_MIN_EVENTS,
) -> CoordinationResult:
    """Build the co-forwarding coordination network over ``channel_ids``.

    Queries the same message universe as the citation graph: alive messages,
    inside the export window, period-aware via ``channel_cutoff_q()`` (a
    message counts only while its channel is in an in-target period), and
    never self-forwards. The origin channel does not need to be in
    ``channel_ids`` — two in-target channels co-forwarding an out-of-target
    origin is still coordination *between them*.

    Node scores (post-filter, i.e. counted over retained pairs only):

    * ``coordination_partners`` — distinct channels the channel keeps a tie with;
    * ``coordination_strength`` — total co-forwarding events across those ties
      (the sum of the channel's edge weights);
    * ``coordination_ratio`` — share of the channel's forwarded origins that
      were co-forwarded with at least one retained partner, in [0, 1].
    """
    fwd_q = (
        Q(channel_id__in=list(channel_ids))
        & Q(forwarded_from__isnull=False)
        & ~Q(channel_id=F("forwarded_from_id"))
        & Q(date__isnull=False)
        & make_date_q(start_date, end_date)
        & channel_cutoff_q()
    )
    rows = (
        Message.objects.alive()
        .filter(fwd_q)
        .values("channel_id", "forwarded_from_id", "fwd_from_channel_post", "fwd_from_date", "date")
        .iterator()
    )

    # origin key -> {channel_id: earliest forward time}
    first_forward: dict[tuple, dict[int, datetime.datetime]] = {}
    for row in rows:
        if row["fwd_from_channel_post"] is not None:
            origin_key = (row["forwarded_from_id"], "post", row["fwd_from_channel_post"])
        elif row["fwd_from_date"] is not None:
            origin_key = (row["forwarded_from_id"], "date", row["fwd_from_date"])
        else:
            continue  # origin message unidentifiable
        per_channel = first_forward.setdefault(origin_key, {})
        current = per_channel.get(row["channel_id"])
        if current is None or row["date"] < current:
            per_channel[row["channel_id"]] = row["date"]

    window = datetime.timedelta(seconds=window_seconds)
    sorted_entries: dict[tuple, list[tuple[datetime.datetime, int]]] = {
        okey: sorted((t, ch) for ch, t in per.items()) for okey, per in first_forward.items() if len(per) > 1
    }

    pair_events: Counter[tuple[int, int]] = Counter()
    for entries in sorted_entries.values():
        # set(): guard against counting a pair twice for one origin (cannot
        # happen with deduped entries, but the invariant is cheap to enforce).
        for pair in set(_window_pairs(entries, window)):
            pair_events[pair] += 1

    kept = {pair: n for pair, n in pair_events.items() if n >= min_events}

    # Second pass: per-channel coordinated-origin sets, counted over retained pairs only.
    coordinated_origins: dict[int, set[tuple]] = {}
    for okey, entries in sorted_entries.items():
        for a, b in set(_window_pairs(entries, window)):
            if (a, b) in kept:
                coordinated_origins.setdefault(a, set()).add(okey)
                coordinated_origins.setdefault(b, set()).add(okey)

    origins_forwarded: Counter[int] = Counter()
    for per_channel in first_forward.values():
        for ch in per_channel:
            origins_forwarded[ch] += 1

    partners: Counter[int] = Counter()
    strength: Counter[int] = Counter()
    for (a, b), n in kept.items():
        partners[a] += 1
        partners[b] += 1
        strength[a] += n
        strength[b] += n

    node_scores: dict[str, dict[str, float]] = {}
    for ch in partners:
        total = origins_forwarded.get(ch, 0)
        coordinated = len(coordinated_origins.get(ch, ()))
        node_scores[str(ch)] = {
            "partners": partners[ch],
            "strength": strength[ch],
            "ratio": round(coordinated / total, 4) if total else 0.0,
        }

    edges = sorted(((str(a), str(b), n) for (a, b), n in kept.items()), key=lambda e: (int(e[0]), int(e[1])))
    return CoordinationResult(
        edges=edges,
        node_scores=node_scores,
        channels_seen=len(origins_forwarded),
        origins_seen=len(first_forward),
        window_seconds=window_seconds,
        min_events=min_events,
    )


def build_nx_graph(result: CoordinationResult, main_graph: nx.DiGraph) -> nx.DiGraph:
    """NetworkX graph of the coordination ties, ready for the layout pipeline.

    Coordination is symmetric, so every tie is materialised in both directions
    (the map viewer then lists partners under "Two ways connections", which is
    the truthful rendering). Node ``data`` dicts are shared with the main
    citation graph so colours and metadata stay identical across the two maps.
    """
    g: nx.DiGraph = nx.DiGraph()
    for node_id in result.node_ids:
        data = main_graph.nodes[node_id].get("data") if main_graph.has_node(node_id) else None
        g.add_node(node_id, data=data)
    for a, b, n in result.edges:
        g.add_edge(a, b, weight=float(n))
        g.add_edge(b, a, weight=float(n))
    return g
