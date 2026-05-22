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
from collections.abc import Callable

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


def recompute_channel(
    channel_id: int,
    *,
    weights: dict[str, float] = DEFAULT_WEIGHTS,
    min_sample: int = MIN_SAMPLE,
    recency_days: int | None = RECENCY_DAYS,
) -> int:
    """Recompute z-scores and ``interest_score`` for every alive ``Message``
    in *channel_id*. Returns the number of messages written.

    The composite uses *partial renormalisation*: a message missing one facet
    (e.g. a sticker post Telegram never reports views for) is scored on the
    remaining facets with their weights rescaled to sum to 1, so it is not
    penalised against text posts. ``interest_score`` is NULL only when every
    facet z-score is NULL.
    """
    normalised = _normalised_weights(weights)
    qs = Message.objects.alive().filter(channel_id=channel_id)
    if recency_days is not None and recency_days > 0:
        cutoff = timezone.now() - datetime.timedelta(days=recency_days)
        qs = qs.filter(date__gte=cutoff)
    rows = list(qs.values_list("pk", "views", "forwards", "total_reactions"))
    if not rows:
        return 0

    stats: dict[str, tuple[float, float] | None] = {}
    for facet in _FACET_FIELDS:
        values = [r[_FACET_IDX[facet]] for r in rows if r[_FACET_IDX[facet]] is not None]
        stats[facet] = _facet_stats(values, min_sample)

    now = timezone.now()
    updates: list[Message] = []
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
        updates.append(
            Message(
                pk=pk,
                z_views=z_per_facet["views"],
                z_forwards=z_per_facet["forwards"],
                z_reactions=z_per_facet["reactions"],
                interest_score=interest_score,
                interest_scored_at=now,
            )
        )

    Message.objects.bulk_update(
        updates,
        ["z_views", "z_forwards", "z_reactions", "interest_score", "interest_scored_at"],
        batch_size=1000,
    )
    return len(updates)


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
