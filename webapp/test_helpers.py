"""Test-only factories for the time-bounded label model.

The legacy ``Organization`` / ``ChannelAttribution`` models were replaced by
``LabelGroup`` / ``Label`` / ``ChannelLabel``. ``make_channel`` keeps fixtures
terse: pass ``label=`` (optionally with ``attribution_start`` / ``attribution_end``)
and it creates the channel plus one label period — the open-ended ``(None, None)``
period reproduces the old "belongs to this label for all time" behaviour.
``label=None`` (or omitted) creates an unlabelled channel.

``make_label`` creates a :class:`~webapp.models.Label` in the primary
"Organization" partition group (created on first use), so labels behave like the
former organizations: at most one per channel at a time, supplying the channel's
representative label, node colour, and in-target status.
"""

from __future__ import annotations

import datetime

from webapp.models import Channel, ChannelLabel, Label, LabelGroup


def label_group(
    name: str = "Organization",
    *,
    is_partition: bool = True,
    is_primary: bool = True,
    color: str = "#000000",
) -> LabelGroup:
    """Get-or-create a ``LabelGroup`` (default: the primary 'Organization' partition group)."""
    group, _ = LabelGroup.objects.get_or_create(
        name=name,
        defaults={"is_partition": is_partition, "is_primary": is_primary, "color": color},
    )
    return group


def make_label(
    name: str,
    color: str = "#000000",
    is_in_target: bool = True,
    group: LabelGroup | None = None,
) -> Label:
    """Create a ``Label`` in ``group`` (default: the primary 'Organization' group)."""
    return Label.objects.create(group=group or label_group(), name=name, color=color, is_in_target=is_in_target)


def attribute(
    channel: Channel,
    label: Label,
    start: datetime.date | None = None,
    end: datetime.date | None = None,
) -> ChannelLabel:
    """Attach one label period to ``channel``."""
    return ChannelLabel.objects.create(channel=channel, label=label, start=start, end=end)


def make_channel(
    label: Label | None = None,
    attribution_start: datetime.date | None = None,
    attribution_end: datetime.date | None = None,
    **kwargs,
) -> Channel:
    """Create a Channel and, when ``label`` is given, one label period."""
    channel = Channel.objects.create(**kwargs)
    if label is not None:
        attribute(channel, label, attribution_start, attribution_end)
    return channel
