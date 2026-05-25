"""Test-only factories for the time-bounded attribution model.

``Channel.organization`` (FK) and ``Channel.out_of_target_after`` were replaced by
the :class:`~webapp.models.ChannelAttribution` through-model. ``make_channel``
keeps test fixtures terse: pass ``organization=`` (optionally with
``attribution_start`` / ``attribution_end``) and it creates the channel plus one
attribution period — the open-ended ``(None, None)`` period reproduces the old
"belongs to this org for all time" behaviour. ``organization=None`` (or omitted)
creates an unattributed channel.
"""

from __future__ import annotations

import datetime

from webapp.models import Channel, ChannelAttribution, Organization


def attribute(
    channel: Channel,
    organization: Organization,
    start: datetime.date | None = None,
    end: datetime.date | None = None,
) -> ChannelAttribution:
    """Attach one attribution period to ``channel``."""
    return ChannelAttribution.objects.create(channel=channel, organization=organization, start=start, end=end)


def make_channel(
    organization: Organization | None = None,
    attribution_start: datetime.date | None = None,
    attribution_end: datetime.date | None = None,
    **kwargs,
) -> Channel:
    """Create a Channel and, when ``organization`` is given, one attribution period."""
    # ``out_of_target_after`` used to be a Channel field; map a legacy kwarg onto the period end.
    attribution_end = kwargs.pop("out_of_target_after", attribution_end)
    channel = Channel.objects.create(**kwargs)
    if organization is not None:
        attribute(channel, organization, attribution_start, attribution_end)
    return channel
