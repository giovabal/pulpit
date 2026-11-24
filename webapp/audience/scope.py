"""What every Audience-page section counts: the scope channels, their posts, the kept commenters' replies.

Scope (:class:`Scope`): the in-target channels (those of the label ``voice`` when the page's
``?filter=`` names one; exactly ``channel_ids`` for an export — its observed in-target channels), their
alive posts dated inside their in-target periods (the graph pipeline's ``channel_cutoff_q`` chokepoint,
applied to the post) and inside ``start`` / ``end`` when given, and the replies to those posts written by
the user accounts :mod:`webapp.commenters` keeps — Telegram bots and bulk posters left out.
"""

from __future__ import annotations

import datetime
from dataclasses import dataclass
from typing import NamedTuple

from django.db.models import QuerySet
from django.utils import timezone

from network.event_impact import LabelMembership, partition_groups
from network.parameters import FixedParameter
from network.utils import channel_cutoff_q, make_date_q
from webapp.commenters import audience_replies, excluded_sender_ids
from webapp.models import Channel, Label, Message, MessageReply


@dataclass(frozen=True)
class Scope:
    """The channels and days a section counts.

    ``voice`` — a label (the page's ``?filter=``): only its channels (``in_label``). ``channel_ids``
    — exactly these channels instead of the in-target set (``structural_analysis`` passes its observed
    in-target nodes, which already honour ``--channel-types``, ``--filter-labels`` and the lost / private
    switches). ``start`` / ``end`` — inclusive local-date bounds on the post date (``--startdate`` /
    ``--enddate``). The default is the Audience page without a filter.
    """

    voice: Label | None = None
    channel_ids: frozenset[int] | None = None
    start: datetime.date | None = None
    end: datetime.date | None = None


def scope_channels(scope: Scope | None = None) -> QuerySet[Channel]:
    """The in-target channels (or ``scope.channel_ids``), limited to those under ``scope.voice`` when given."""
    scope = scope or Scope()
    if scope.channel_ids is not None:
        channels = Channel.objects.filter(pk__in=scope.channel_ids)
    else:
        channels = Channel.objects.in_target()
    return channels.in_label(scope.voice) if scope.voice is not None else channels


def scope_posts(scope: Scope | None = None) -> QuerySet[Message]:
    """The scope channels' alive posts dated inside their in-target periods (and the scope's dates)."""
    scope = scope or Scope()
    return (
        Message.objects.alive()
        .filter(channel__in=scope_channels(scope).values("pk"))
        .filter(channel_cutoff_q())
        .filter(make_date_q(scope.start, scope.end))
    )


def scope_replies(scope: Scope | None = None, excluded: set[int] | None = None) -> QuerySet[MessageReply]:
    """Replies by kept accounts to :func:`scope_posts`."""
    return audience_replies(MessageReply.objects.filter(parent_message__in=scope_posts(scope).values("pk")), excluded)


class Reply(NamedTuple):
    """One reply in scope: who wrote it, on which channel's post, and when (local days)."""

    sender_id: int
    channel_id: int
    post_id: int
    post_day: datetime.date | None
    day: datetime.date | None  # the reply's own day, else its post's
    when: datetime.datetime | None  # the reply's own timestamp, else its post's


def _local_day(value: datetime.datetime | None) -> datetime.date | None:
    return timezone.localdate(value) if value is not None else None


def reply_records(scope: Scope | None = None, excluded: set[int] | None = None) -> list[Reply]:
    """Every reply in scope, as :class:`Reply` tuples."""
    rows = scope_replies(scope, excluded).values_list(
        "sender_id", "parent_message__channel_id", "parent_message_id", "parent_message__date", "date"
    )
    out = []
    for sender_id, channel_id, post_id, post_date, date in rows:
        when = date or post_date
        out.append(Reply(sender_id, channel_id, post_id, _local_day(post_date), _local_day(when), when))
    return out


def coverage(scope: Scope | None = None) -> dict:
    """How much of the scope the commenters can describe: channels in scope, with a discussion group,
    with comments in scope, and the accounts the flags leave out."""
    channels = scope_channels(scope)
    excluded = excluded_sender_ids()
    posts = scope_posts(scope).values("pk")
    return {
        "scope_channels": channels.count(),
        "channels_with_discussion": channels.filter(linked_chat_id__isnull=False).count(),
        "channels_with_comments": (scope_replies(scope, excluded).values("parent_message__channel").distinct().count()),
        "left_out_accounts": (
            MessageReply.objects.filter(parent_message__in=posts, sender_id__in=list(excluded))
            .values("sender_id")
            .distinct()
            .count()
            if excluded
            else 0
        ),
    }


#: A partition label group is reported only when its labels cover at least this share of the replies:
#: below it the group describes a minority of the commenters (on a real corpus, *Type* covered 21%).
MIN_GROUP_COVERAGE = 0.5

FIXED_PARAMETERS: tuple[FixedParameter, ...] = (
    FixedParameter(
        name="Audience: label-group coverage floor",
        value=MIN_GROUP_COVERAGE,
        scope="audience",
        affects="A partition label group is reported in Breadth and Audience overlap only when its labels cover "
        "at least this share of the replies.",
        source="webapp/audience/scope.py: MIN_GROUP_COVERAGE",
    ),
)


class LabelResolver:
    """The label each partition group gives a channel on a day (container groups through their
    children), cached per (group, channel, day)."""

    def __init__(self, channel_ids: list[int]) -> None:
        self.groups = [
            (group_id, name, LabelMembership(channel_ids, group_id, is_container))
            for group_id, name, is_container in partition_groups()
        ]
        self._cache: dict[tuple[int, int, datetime.date | None], int | None] = {}
        self.label_names = dict(Label.objects.values_list("pk", "name"))
        self.label_colors = dict(Label.objects.values_list("pk", "color"))

    def label(self, group_index: int, channel_id: int, day: datetime.date | None) -> int | None:
        if day is None:
            return None
        key = (group_index, channel_id, day)
        if key not in self._cache:
            self._cache[key] = self.groups[group_index][2].at(channel_id, day)
        return self._cache[key]
