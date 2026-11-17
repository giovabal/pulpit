"""Audience statistics over the commenters of in-target channels — the Audience page (``/audience/``).

One module per section of the page; :mod:`.scope` holds what they all count. ``SECTIONS`` lists them in
menu order: ``(slug, title, compute function, template)``.
"""

from .breadth import breadth
from .channel_commenters import channel_commenters
from .overlap import overlap
from .participation import (
    ACTIVITY_BINS,
    ADJBOX_A,
    ADJBOX_B,
    ADJBOX_COEF,
    LORENZ_POINTS,
    MIN_CONCENTRATION_COMMENTERS,
    TOP_SHARES,
    activity_bins,
    adjusted_fences,
    concentration,
    effective_number,
    gini,
    lorenz_points,
    medcouple,
    participation,
    top_share,
)
from .retention import retention
from .scope import coverage, reply_records, scope_channels, scope_posts, scope_replies

SECTIONS = (
    ("participation", "Participation", participation),
    ("breadth", "Breadth", breadth),
    ("overlap", "Audience overlap", overlap),
    ("retention", "Retention", retention),
    ("channel-commenters", "Channels as commenters", channel_commenters),
)

__all__ = [
    "ACTIVITY_BINS",
    "ADJBOX_A",
    "ADJBOX_B",
    "ADJBOX_COEF",
    "LORENZ_POINTS",
    "MIN_CONCENTRATION_COMMENTERS",
    "SECTIONS",
    "TOP_SHARES",
    "activity_bins",
    "adjusted_fences",
    "breadth",
    "channel_commenters",
    "concentration",
    "coverage",
    "effective_number",
    "gini",
    "lorenz_points",
    "medcouple",
    "overlap",
    "participation",
    "reply_records",
    "retention",
    "scope_channels",
    "scope_posts",
    "scope_replies",
    "top_share",
]
