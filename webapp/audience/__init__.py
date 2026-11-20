"""Audience statistics over the commenters of in-target channels — the Audience page (``/audience/``).

One module per section of the page; :mod:`.scope` holds what they all count. ``SECTIONS`` lists them in
menu order: ``(slug, title, compute function)``; each compute function takes a :class:`Scope` (default: every
in-target channel). :mod:`.tables` lays each section's main table out for the CSVs and the export's XLSX;
``network.audience_layer`` puts the sections into a ``structural_analysis`` export.
"""

from webapp.commenters import FIXED_PARAMETERS as _COMMENTER_FIXED_PARAMETERS

from .breadth import FIXED_PARAMETERS as _BREADTH_FIXED_PARAMETERS, breadth
from .channel_commenters import channel_commenters
from .overlap import FIXED_PARAMETERS as _OVERLAP_FIXED_PARAMETERS, overlap
from .participation import (
    ACTIVITY_BINS,
    ADJBOX_A,
    ADJBOX_B,
    ADJBOX_COEF,
    FIXED_PARAMETERS as _PARTICIPATION_FIXED_PARAMETERS,
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
from .retention import FIXED_PARAMETERS as _RETENTION_FIXED_PARAMETERS, retention
from .scope import (
    FIXED_PARAMETERS as _SCOPE_FIXED_PARAMETERS,
    Scope,
    coverage,
    reply_records,
    scope_channels,
    scope_posts,
    scope_replies,
)

# Collected by network.parameters (PARAMETERS.md of an export with --audience), in page order.
FIXED_PARAMETERS = (
    *_COMMENTER_FIXED_PARAMETERS,
    *_SCOPE_FIXED_PARAMETERS,
    *_PARTICIPATION_FIXED_PARAMETERS,
    *_BREADTH_FIXED_PARAMETERS,
    *_OVERLAP_FIXED_PARAMETERS,
    *_RETENTION_FIXED_PARAMETERS,
)

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
    "FIXED_PARAMETERS",
    "LORENZ_POINTS",
    "MIN_CONCENTRATION_COMMENTERS",
    "SECTIONS",
    "TOP_SHARES",
    "Scope",
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
