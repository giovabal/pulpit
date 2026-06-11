"""Structural interest scoring for messages.

Computes per-message **cross-community reach** *C* — the number of distinct
communities among a post's forwarders. Telegram exposes only depth-1 forwarding,
so the true structural-virality (Wiener-index) metric of Goel, Anderson, Hofman &
Watts (*The structural virality of online diffusion*, Management Science 2016)
cannot be reconstructed; *C* is a breadth-based proxy in that spirit, **not** that
metric. Also computes **authority-weighted reach** *D* (Cha, Haddadi, Benevenuto &
Gummadi, *Measuring user influence in Twitter*, ICWSM 2010, "weighted indegree"
analogue) by walking the ``(forwarded_from, fwd_from_channel_post)`` join.

Output is a JSON-serialisable dict written to
``exports/<name>/data/interest_structural.json`` by
``network.exporter.write_interest_structural_json``. See the plan at
``/home/jo/.claude/plans/i-want-to-implement-radiant-lovelace.md`` §4 for the
edge cases (out-of-target forwarders, self-forwards, album heads, window).
"""

from __future__ import annotations

import datetime
import logging
from collections import defaultdict
from collections.abc import Callable
from typing import Any

from django.db.models import F
from django.utils import timezone

from network.utils import GraphData
from webapp.models import Channel, Message

import networkx as nx  # noqa: F401  (kept for type-symmetry with sister modules)

logger = logging.getLogger(__name__)

DEFAULT_TOP_PER_CHANNEL: int = 50
_FORWARDER_CHUNK: int = 5000


def compute_interest_structural(
    graph_data: GraphData,
    channel_dict: dict[str, Any],
    *,
    community_strategy: str,
    authority_key: str = "pagerank",
    window_days: int = 30,
    include_mentions: bool = False,
    top_n_per_channel: int = DEFAULT_TOP_PER_CHANNEL,
    progress: Callable[[str], None] | None = None,
    window_filter: dict[str, Any] | None = None,
    interest_score_override: dict[tuple[int, int], float | None] | None = None,
) -> dict[str, Any]:
    """Compute per-message C and D and emit a JSON-serialisable payload.

    Parameters
    ----------
    graph_data
        ``GraphData`` dict returned by ``exporter.build_graph_data`` *after*
        ``_compute_measures`` has populated the authority key.
    channel_dict
        The ``{str(pk): {channel, data}}`` dict from ``graph_builder.build_graph``;
        ``data["communities"][strategy_key]`` holds the community label.
    community_strategy
        Strategy name (e.g. ``"LEIDEN_DIRECTED"``); lowercased internally to
        match the storage key used by ``community.apply_to_graph``.
    authority_key
        Node-attribute key holding the authority score (``"pagerank"`` by
        default; fallback chain handled by the caller).
    window_days
        Forwards beyond this many days from the origin's posting date are
        dropped. ``0`` disables the window.
    include_mentions
        Accepted for forward compatibility; not yet implemented. Mentions in
        ``Message.references`` are message→channel rather than
        message→message and need separate design work.
    top_n_per_channel
        Size of each per-channel top list.
    progress
        Optional callback for stage labels.
    window_filter
        Optional Django ORM filter kwargs (production passes the ``__date``
        transform: ``{"date__date__gte": ..., "date__date__lte": ...}``) applied
        to both forwarder queries. Targets the forwarder row's
        ``date``, not the origin's — so an older origin counts if it was
        forwarded inside the window. Without this, C, D and the forwarder
        counts are computed over all-time forwards regardless of the export's
        date scope.
    interest_score_override
        Optional ``{(channel_id, telegram_id): interest_score}`` map that
        takes precedence over ``Message.interest_score`` when emitting the
        per-message ``interest_score`` field. Lets the caller substitute a
        windowed hot-layer recompute without persisting it.
    """
    if include_mentions:
        logger.warning(
            "interest_structural: include_mentions=True is accepted but not yet "
            "implemented. Telegram's references are message→channel, not "
            "message→message, and a faithful translation needs separate design."
        )

    if progress:
        progress("preparing channel maps")
    strategy_key = community_strategy.lower()
    comm_by_pk: dict[int, Any] = {}
    auth_by_pk: dict[int, float] = {}
    for node_id, entry in channel_dict.items():
        comm_label = (entry["data"].get("communities") or {}).get(strategy_key)
        if comm_label is not None:
            comm_by_pk[int(node_id)] = comm_label
    for node in graph_data.get("nodes") or ():
        val = node.get(authority_key)
        if val is None:
            continue
        try:
            auth_by_pk[int(node["id"])] = float(val)
        except (TypeError, ValueError):
            continue

    in_target_pks: set[int] = set(Channel.objects.in_target().values_list("pk", flat=True))

    if progress:
        progress("collecting in-target forwarder rows")
    forwarders_by_origin: dict[tuple[int, int], list[tuple[int, datetime.datetime | None]]] = defaultdict(list)
    out_forwarders_by_origin: dict[tuple[int, int], list[tuple[int, datetime.datetime | None]]] = defaultdict(list)

    in_target_qs = Message.objects.alive().filter(
        channel_id__in=in_target_pks,
        forwarded_from_id__in=in_target_pks,
        fwd_from_channel_post__isnull=False,
    )
    if window_filter:
        in_target_qs = in_target_qs.filter(**window_filter)
    in_target_q = in_target_qs.exclude(channel_id=F("forwarded_from_id")).values_list(
        "channel_id", "forwarded_from_id", "fwd_from_channel_post", "date"
    )
    for fwd_ch, origin_ch, origin_tg_id, fwd_date in in_target_q.iterator(chunk_size=_FORWARDER_CHUNK):
        forwarders_by_origin[(origin_ch, origin_tg_id)].append((fwd_ch, fwd_date))

    if progress:
        progress("counting out-of-target forwarders")
    out_target_qs = Message.objects.alive().filter(
        forwarded_from_id__in=in_target_pks,
        fwd_from_channel_post__isnull=False,
    )
    if window_filter:
        out_target_qs = out_target_qs.filter(**window_filter)
    # Collected with the same shape as the in-target side (forwarder channel + date)
    # so the consumer can apply the identical reaction window and per-channel dedup —
    # the two columns are rendered as a comparable pair, and counting raw forward
    # *messages* with no window here would systematically inflate the out side.
    out_target_q = out_target_qs.exclude(channel_id__in=in_target_pks).values_list(
        "channel_id", "forwarded_from_id", "fwd_from_channel_post", "date"
    )
    for fwd_ch, origin_ch, origin_tg_id, fwd_date in out_target_q.iterator(chunk_size=_FORWARDER_CHUNK):
        out_forwarders_by_origin[(origin_ch, origin_tg_id)].append((fwd_ch, fwd_date))

    if interest_score_override is None:
        hot_layer_scope = "all-time"
    elif window_filter:
        hot_layer_scope = _scope_label(window_filter)
    else:
        hot_layer_scope = "overridden"
    structural_scope = _scope_label(window_filter)

    if not forwarders_by_origin:
        return _empty_payload(
            community_strategy=strategy_key,
            authority_key=authority_key,
            window_days=window_days,
            include_mentions=include_mentions,
            hot_layer_scope=hot_layer_scope,
            structural_scope=structural_scope,
        )

    if progress:
        progress("fetching origin metadata")
    origins_by_channel: dict[int, list[int]] = defaultdict(list)
    for ch_pk, tg_id in forwarders_by_origin:
        origins_by_channel[ch_pk].append(tg_id)
    origin_meta: dict[tuple[int, int], dict[str, Any]] = {}
    for ch_pk, tg_ids in origins_by_channel.items():
        rows = Message.objects.filter(channel_id=ch_pk, telegram_id__in=tg_ids).values_list(
            "telegram_id", "date", "grouped_id", "interest_score"
        )
        for tg_id, date, grouped_id, interest_score in rows:
            if interest_score_override is not None:
                interest_score = interest_score_override.get((ch_pk, tg_id))
            origin_meta[(ch_pk, tg_id)] = {
                "date": date,
                "grouped_id": grouped_id,
                "interest_score": interest_score,
            }

    if progress:
        progress("scoring origins")
    by_message: list[dict[str, Any]] = []

    def _within_window(
        rows: list[tuple[int, datetime.datetime | None]], origin_date: datetime.datetime | None
    ) -> list[tuple[int, datetime.datetime | None]]:
        if window_days > 0 and origin_date is not None:
            cutoff = origin_date + datetime.timedelta(days=window_days)
            return [(fid, fd) for fid, fd in rows if fd is not None and fd <= cutoff]
        return list(rows)

    for key, forwarders in forwarders_by_origin.items():
        origin_ch, origin_tg_id = key
        meta = origin_meta.get(key) or {}
        origin_date: datetime.datetime | None = meta.get("date")
        grouped_id = meta.get("grouped_id")
        interest_score = meta.get("interest_score")
        filtered = _within_window(forwarders, origin_date)
        if not filtered:
            continue
        forwarder_pks = {pk for pk, _ in filtered}
        # Same window + distinct-channel dedup as the in-target side, so the two
        # columns count the same thing.
        out_forwarder_pks = {pk for pk, _ in _within_window(out_forwarders_by_origin.get(key, []), origin_date)}
        c_value = len({comm_by_pk[pk] for pk in forwarder_pks if pk in comm_by_pk})
        d_value = sum(auth_by_pk.get(pk, 0.0) for pk in forwarder_pks)
        by_message.append(
            {
                "channel_pk": origin_ch,
                "telegram_id": origin_tg_id,
                "date": origin_date.isoformat() if origin_date else None,
                "grouped_id": grouped_id,
                "c_cross_community": c_value,
                "d_authority_reach": d_value,
                "interest_score": interest_score,
                "forwarder_count_in_target": len(forwarder_pks),
                "forwarder_count_out_of_target": len(out_forwarder_pks),
            }
        )

    if progress:
        progress("ranking per channel")
    by_channel_top: dict[str, dict[str, list[dict[str, Any]]]] = {}
    grouped: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for rec in by_message:
        grouped[rec["channel_pk"]].append(rec)

    def _interest_key(rec: dict[str, Any]) -> float:
        v = rec["interest_score"]
        return v if v is not None else float("-inf")

    for ch_pk, recs in grouped.items():
        by_interest = sorted(recs, key=_interest_key, reverse=True)[:top_n_per_channel]
        by_c = sorted(recs, key=lambda r: r["c_cross_community"], reverse=True)[:top_n_per_channel]
        by_channel_top[str(ch_pk)] = {"by_interest": by_interest, "by_cross_community": by_c}

    return {
        "computed_at": timezone.now().isoformat(timespec="seconds"),
        "community_strategy": strategy_key,
        "authority_key": authority_key,
        "window_days": window_days,
        "include_mentions": include_mentions,
        "hot_layer_scope": hot_layer_scope,
        "structural_scope": structural_scope,
        "forwarder_window_policy": "forwarder-date",
        "by_message": by_message,
        "by_channel_top": by_channel_top,
    }


def _scope_label(window_filter: dict[str, Any] | None) -> str:
    """Render a window filter as a human-readable scope string for the payload."""
    if not window_filter:
        return "all-time"
    # Production builds the filter with the ``__date`` transform
    # (``_date_window_filter`` → ``date__date__gte`` / ``date__date__lte``);
    # tolerate the plain ``date__gte`` / ``date__lte`` form too.
    start = window_filter.get("date__date__gte") or window_filter.get("date__gte")
    end = (
        window_filter.get("date__date__lte")
        or window_filter.get("date__date__lt")
        or window_filter.get("date__lte")
        or window_filter.get("date__lt")
    )
    if start is None and end is None:
        return "windowed"
    return f"window {_iso(start)}..{_iso(end)}"


def _iso(value: Any) -> str:
    if value is None:
        return "…"
    if isinstance(value, datetime.datetime):
        return value.date().isoformat()
    if isinstance(value, datetime.date):
        return value.isoformat()
    return str(value)


def _empty_payload(
    *,
    community_strategy: str,
    authority_key: str,
    window_days: int,
    include_mentions: bool,
    hot_layer_scope: str = "all-time",
    structural_scope: str = "all-time",
) -> dict[str, Any]:
    return {
        "computed_at": timezone.now().isoformat(timespec="seconds"),
        "community_strategy": community_strategy,
        "authority_key": authority_key,
        "window_days": window_days,
        "include_mentions": include_mentions,
        "hot_layer_scope": hot_layer_scope,
        "structural_scope": structural_scope,
        "forwarder_window_policy": "forwarder-date",
        "by_message": [],
        "by_channel_top": {},
    }
