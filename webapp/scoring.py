"""Per-channel engagement scoring for ``Message`` rows.

Computes the *hot* layer of the message-interestingness pipeline: z-scores of
views / forwards / reactions normalised inside each channel (Salganik, Dodds &
Watts, *Experimental study of inequality and unpredictability in an artificial
cultural market*, Science 2006) plus a weighted composite ``interest_score``
with literature defaults (Suh, Hong, Pirolli & Chi 2010; Cha, Haddadi,
Benevenuto & Gummadi 2010).

The structural layer (cross-community reach, authority-weighted reach) lives
in ``network/`` because it depends on community labels and centrality scores
produced by ``structural_analysis``.
"""

from __future__ import annotations

import datetime
import math
from collections import defaultdict
from collections.abc import Callable, Iterable

from django.utils import timezone

from webapp.models import Message

# Weighting follows Suh et al. 2010 / Cha et al. 2010: reactions weigh
# heaviest (deliberate engagement), forwards next (rebroadcast intent), views
# least (passive exposure).
DEFAULT_WEIGHTS: dict[str, float] = {"reactions": 0.5, "forwards": 0.3, "views": 0.2}
# Channels with fewer than this many alive messages get NULL interest scores
# (cold-start: per-channel std becomes too noisy to z-score against).
MIN_SAMPLE: int = 30
# Recency window for the per-channel baseline. None = all-time.
RECENCY_DAYS: int | None = None

# Message field name backing each facet.
_FACET_FIELDS: dict[str, str] = {
    "views": "views",
    "forwards": "forwards",
    "reactions": "total_reactions",
}
# Position of each facet inside the (pk, views, forwards, total_reactions) tuple.
_FACET_IDX: dict[str, int] = {"views": 1, "forwards": 2, "reactions": 3}


def _normalised_weights(weights: dict[str, float]) -> dict[str, float]:
    if any(w < 0 for w in weights.values()):
        raise ValueError("weights must be non-negative")
    total = sum(weights.values())
    if total <= 0:
        raise ValueError("at least one weight must be positive")
    return {k: v / total for k, v in weights.items()}


def _facet_stats(values: list[int], min_sample: int) -> tuple[float, float] | None:
    """Population mean and stddev when the sample is big enough and non-degenerate."""
    if len(values) < min_sample:
        return None
    mean = sum(values) / len(values)
    var = sum((v - mean) ** 2 for v in values) / len(values)
    std = math.sqrt(var)
    if std == 0:
        return None
    return mean, std


def score_messages(
    rows: Iterable[tuple[int, int | None, int | None, int | None]],
    *,
    weights: dict[str, float] = DEFAULT_WEIGHTS,
    min_sample: int = MIN_SAMPLE,
) -> dict[int, tuple[float | None, float | None, float | None, float | None]]:
    """Pure scoring core: ``(pk, views, forwards, total_reactions)`` rows in,
    ``{pk: (z_views, z_forwards, z_reactions, interest_score)}`` out.

    Does not touch the database. Callers decide whether to persist the result
    (``recompute_channel`` does; the export path keeps it in memory).

    The composite uses *partial renormalisation*: a message missing one facet
    (e.g. a sticker post Telegram never reports views for) is scored on the
    remaining facets with their weights rescaled to sum to 1, so it is not
    penalised against text posts. ``interest_score`` is NULL only when every
    facet z-score is NULL.
    """
    normalised = _normalised_weights(weights)
    rows = list(rows)
    if not rows:
        return {}

    stats: dict[str, tuple[float, float] | None] = {}
    for facet in _FACET_FIELDS:
        values = [r[_FACET_IDX[facet]] for r in rows if r[_FACET_IDX[facet]] is not None]
        stats[facet] = _facet_stats(values, min_sample)

    scored: dict[int, tuple[float | None, float | None, float | None, float | None]] = {}
    for row in rows:
        pk = row[0]
        z_per_facet: dict[str, float | None] = {"views": None, "forwards": None, "reactions": None}
        score_sum = 0.0
        weight_sum = 0.0
        for facet in _FACET_FIELDS:
            stat = stats[facet]
            if stat is None:
                continue
            value = row[_FACET_IDX[facet]]
            if value is None:
                continue
            mean, std = stat
            z = (value - mean) / std
            z_per_facet[facet] = z
            score_sum += normalised[facet] * z
            weight_sum += normalised[facet]
        interest_score = score_sum / weight_sum if weight_sum > 0 else None
        scored[pk] = (
            z_per_facet["views"],
            z_per_facet["forwards"],
            z_per_facet["reactions"],
            interest_score,
        )
    return scored


def recompute_channel(
    channel_id: int,
    *,
    weights: dict[str, float] = DEFAULT_WEIGHTS,
    min_sample: int = MIN_SAMPLE,
    recency_days: int | None = RECENCY_DAYS,
) -> int:
    """Recompute z-scores and ``interest_score`` for every alive ``Message``
    in *channel_id* and persist them. Returns the number of messages written.
    """
    qs = Message.objects.alive().filter(channel_id=channel_id)
    if recency_days is not None and recency_days > 0:
        cutoff = timezone.now() - datetime.timedelta(days=recency_days)
        qs = qs.filter(date__gte=cutoff)
    rows = list(qs.values_list("pk", "views", "forwards", "total_reactions"))
    scored = score_messages(rows, weights=weights, min_sample=min_sample)
    if not scored:
        return 0

    now = timezone.now()
    updates = [
        Message(
            pk=pk,
            z_views=zv,
            z_forwards=zf,
            z_reactions=zr,
            interest_score=score,
            interest_scored_at=now,
        )
        for pk, (zv, zf, zr, score) in scored.items()
    ]
    Message.objects.bulk_update(
        updates,
        ["z_views", "z_forwards", "z_reactions", "interest_score", "interest_scored_at"],
        batch_size=1000,
    )
    return len(updates)


def score_messages_for_window(
    message_qs,
    *,
    weights: dict[str, float] = DEFAULT_WEIGHTS,
    min_sample: int = MIN_SAMPLE,
) -> dict[tuple[int, int], float | None]:
    """In-memory windowed scoring for export sites.

    Groups *message_qs* by channel, scores each channel independently with
    :func:`score_messages`, and returns ``{(channel_id, telegram_id):
    interest_score}`` so callers can join against per-message keys
    (``compute_interest_structural`` uses exactly that shape).

    The returned mapping is empty for channels that fail the ``min_sample``
    cold-start floor — narrow windows hit this often and the consumer is
    expected to render those as a missing-Interest column.
    """
    grouped: dict[int, list[tuple[int, int | None, int | None, int | None]]] = defaultdict(list)
    tg_by_pk: dict[int, tuple[int, int]] = {}
    for pk, channel_id, telegram_id, views, forwards, total_reactions in message_qs.values_list(
        "pk", "channel_id", "telegram_id", "views", "forwards", "total_reactions"
    ):
        grouped[channel_id].append((pk, views, forwards, total_reactions))
        tg_by_pk[pk] = (channel_id, telegram_id)

    out: dict[tuple[int, int], float | None] = {}
    for rows in grouped.values():
        scored = score_messages(rows, weights=weights, min_sample=min_sample)
        for pk, (_zv, _zf, _zr, score) in scored.items():
            out[tg_by_pk[pk]] = score
    return out


def recompute_all_channels(
    *,
    weights: dict[str, float] = DEFAULT_WEIGHTS,
    min_sample: int = MIN_SAMPLE,
    recency_days: int | None = RECENCY_DAYS,
    on_progress: Callable[[int, int, int], None] | None = None,
) -> tuple[int, int]:
    """Recompute scores for every channel that has at least one alive message.

    Returns ``(channels_touched, messages_updated)``. ``on_progress`` is
    invoked as ``(channel_ix, channel_total, messages_updated_for_channel)``.
    """
    channel_ids = list(Message.objects.alive().values_list("channel_id", flat=True).distinct())
    total_messages = 0
    for ix, channel_id in enumerate(channel_ids, start=1):
        n = recompute_channel(channel_id, weights=weights, min_sample=min_sample, recency_days=recency_days)
        total_messages += n
        if on_progress is not None:
            on_progress(ix, len(channel_ids), n)
    return len(channel_ids), total_messages
