"""The home page's summary cards split by the labels of one group (``?split=<group id>``).

One table per card, its rows the lines the split charts draw (:class:`stats.split.LabelSplit`), its columns the
card's figures (:func:`webapp.cache.compute_home_summary`, same definitions). A message counts under its
channel's label on the message's date, a reply under its post's; a channel itself, and its subscribers, under
its label today (its latest past one, else its earliest). Columns add up to the card, except unique commenters:
an account commenting under two labels counts in both rows.
"""

from collections import defaultdict
from collections.abc import Iterable
from typing import Any

from django.db.models import Count, F, Max, Min, Q, QuerySet, Sum
from django.db.models.functions import TruncDate

from stats.queries import in_scope_messages
from stats.split import LabelSplit
from webapp.commenters import audience_replies, excluded_sender_ids
from webapp.models import Channel, LabelGroup, Message, MessageReply
from webapp.utils.dates import fmt_date

_COMMENTERS_TITLE = (
    "Unique commenters. Accounts commenting under several labels count in each, so this column does not add up."
)


def _compact(value: int) -> str:
    """*value* to three significant figures: 35,195,794 → 35.2M. The full figure goes in the cell's title."""
    for size, suffix in ((1_000_000_000, "B"), (1_000_000, "M"), (1_000, "K")):
        if value >= size:
            scaled = value / size
            return f"{scaled:.0f}{suffix}" if scaled >= 100 else f"{scaled:.1f}{suffix}"
    return f"{value:,}"


def _by_channel(qs: QuerySet, changing: set[int], channel: str, date: str, *distinct: str, **aggregates: Any):
    """``(channel, day, *distinct, *aggregates)`` rows of *qs*, the day only for the channels it matters to."""

    def rows(part: QuerySet, *keys: str) -> Iterable[tuple]:
        part = part.order_by().values_list(*keys, *distinct)
        return part.annotate(**aggregates) if aggregates else part.distinct()

    for channel_id, *values in rows(qs.exclude(**{f"{channel}__in": changing}), channel):
        yield (channel_id, None, *values)
    if changing:
        dated = qs.filter(**{f"{channel}__in": changing}).annotate(split_day=TruncDate(date))
        yield from rows(dated, channel, "split_day")


def compute_home_split(voice, group: LabelGroup) -> dict[str, dict[str, Any]]:
    """``{card key: {"columns": [{"label", "title"}], "rows": [{"label", "color", "cells": [{"text", "title"}]}]}}``."""
    channels = Channel.objects.in_target()
    if voice is not None:
        channels = channels.in_label(voice)
    subscribers = dict(channels.values_list("pk", "participants_count"))
    in_target_pks = channels.values("pk")
    in_scope = in_scope_messages(channels).annotate(day=TruncDate("date"))
    split = LabelSplit(in_scope, group, channel_ids=subscribers)

    # Totals per line; ``figures[name][line]``.
    figures: dict[str, dict[Any, int]] = defaultdict(lambda: defaultdict(int))
    for pk, count in subscribers.items():
        line = split.channel_line(pk)
        figures["channels"][line] += 1
        figures["subscribers"][line] += count or 0

    in_target_forward = Q(forwarded_from__in=in_target_pks) & ~Q(forwarded_from=F("channel"))
    message_figures = {
        "messages": Count("id"),
        "media": Count("id", filter=~Q(media_type__in=["", "none"])),
        "pictures": Count("id", filter=Q(media_type="photo")),
        "videos": Count("id", filter=Q(media_type="video")),
        "views": Sum("views"),
        "fwd_in": Count("id", filter=in_target_forward),
        "fwd_self": Count("id", filter=Q(forwarded_from=F("channel"))),
        "fwd_out": Count("id", filter=Q(forwarded_from__isnull=False) & ~Q(forwarded_from__in=in_target_pks)),
    }
    messages = Message.objects.alive().filter(channel__in=in_target_pks)
    first: dict[Any, Any] = {}
    last: dict[Any, Any] = {}
    for channel_id, day, *values in _by_channel(
        messages, split.changing, "channel_id", "date", **message_figures, first=Min("date"), last=Max("date")
    ):
        line = split.line_of(channel_id, day)
        for name, value in zip(message_figures, values, strict=False):
            figures[name][line] += value or 0
        *_, earliest, latest = values
        if earliest is not None:
            first[line] = min(first.get(line, earliest), earliest)
            last[line] = max(last.get(line, latest), latest)

    mention_figures = {
        "ment_in": Count("id", filter=Q(channel__in=in_target_pks) & ~Q(channel=F("message__channel"))),
        "ment_self": Count("id", filter=Q(channel=F("message__channel"))),
        "ment_out": Count("id", filter=~Q(channel__in=in_target_pks)),
    }
    mentions = Message.references.through.objects.filter(message__channel__in=in_target_pks, message__is_lost=False)
    for channel_id, day, *values in _by_channel(
        mentions, split.changing, "message__channel_id", "message__date", **mention_figures
    ):
        line = split.line_of(channel_id, day)
        for name, value in zip(mention_figures, values, strict=True):
            figures[name][line] += value

    replies = MessageReply.objects.filter(parent_message__channel__in=in_target_pks, parent_message__is_lost=False)
    post = ("parent_message__channel_id", "parent_message__date")
    for channel_id, day, count in _by_channel(replies, split.changing, *post, replies=Count("id")):
        figures["replies"][split.line_of(channel_id, day)] += count
    commenters: dict[Any, set[int]] = defaultdict(set)
    kept = audience_replies(replies, excluded_sender_ids())
    for channel_id, day, sender_id in _by_channel(kept, split.changing, *post, "sender_id"):
        commenters[split.line_of(channel_id, day)].add(sender_id)
    for line, accounts in commenters.items():
        figures["commenters"][line] = len(accounts)

    used = {line for by_line in figures.values() for line, value in by_line.items() if value}
    lines = split.lines(used)

    def table(*columns: tuple[str, ...], compact: str = "") -> dict[str, Any]:
        def cell(name: str, line: Any) -> dict[str, str]:
            value = figures[name].get(line, 0)
            return {"text": _compact(value) if name == compact else f"{value:,}", "title": f"{value:,}"}

        return _table(lines, columns, cell)

    dates = {"first": first, "last": last}
    return {
        "channels": table(("channels", "channels")),
        "messages": table(("messages", "messages"), ("replies", "replies")),
        "media": table(("media", "all"), ("pictures", "pictures"), ("videos", "videos")),
        "views": table(
            ("views", "views"),
            ("subscribers", "subscr."),
            ("commenters", "comm.", _COMMENTERS_TITLE),
            compact="views",
        ),
        "forwards": table(("fwd_in", "in-target"), ("fwd_self", "self"), ("fwd_out", "non-in-target")),
        "mentions": table(("ment_in", "in-target"), ("ment_self", "self"), ("ment_out", "non-in-target")),
        "dates": _table(
            lines,
            (("first", "first"), ("last", "last")),
            lambda name, line: {"text": fmt_date(dates[name][line]) if line in dates[name] else "–", "title": ""},
        ),
    }


def _table(lines: list[tuple[Any, str, str]], columns: Iterable[tuple], cell: Any) -> dict[str, Any]:
    """A card's table; a label's row carries its chart colour (1…), the grey of the other lines otherwise."""
    rows = []
    for index, (line, label, kind) in enumerate(lines, start=1):
        color = index if kind == "label" else "rest"
        rows.append({"label": label, "color": color, "cells": [cell(column[0], line) for column in columns]})
    return {
        "columns": [{"label": column[1], "title": column[2] if len(column) > 2 else ""} for column in columns],
        "rows": rows,
    }
