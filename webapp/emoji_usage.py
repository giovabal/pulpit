"""Custom emoji usage per channel, by pack or by emoji — the analysis side of ``webapp.models.emoji_models``.

A channel *uses* an emoji (and its pack) when its posts draw it. A forward carries its source's
text, custom emoji included, so the uses are split between the channel's **own posts** — no
forward header of any kind (``network.near_copies.forward_header_q``) — and the posts it
**forwarded**: only the first say which emoji the channel itself picks. Reactions with an emoji
on the channel's posts are counted apart, since readers send them (within what the channel
allows). Every figure is computed over the message queryset the caller passes — the in-target
channels' alive messages inside their in-target periods (``scope_messages``) for the pack and
emoji pages, the channel page's own period-scoped messages there. ``level`` picks the grouping:
``"pack"`` rows carry ``pack_id`` (``None`` for emoji whose pack is not resolved yet),
``"emoji"`` rows ``emoji_id``. A pack's ``is_in_target`` classifies it; nothing here filters on it.
"""

import datetime
from collections import defaultdict
from typing import Any

from django.db.models import BooleanField, Case, Count, Exists, Max, Min, OuterRef, QuerySet, Sum, Value, When
from django.db.models.functions import TruncMonth

from network.near_copies import forward_header_q
from network.utils import channel_cutoff_q
from webapp.models import (
    Channel,
    CustomEmoji,
    CustomEmojiPack,
    Message,
    MessageCustomEmoji,
    MessageCustomReaction,
)

#: Emoji shown per pack as its preview: the most used ones in scope.
PREVIEW_SIZE = 5

#: ``level`` → the ``MessageCustomEmoji`` / ``MessageCustomReaction`` field rows are grouped by.
LEVELS: dict[str, str] = {"pack": "emoji__pack_id", "emoji": "emoji_id"}

#: ``?target=`` values of the pack and emoji pages: every pack, or only those in / out of target.
TARGET_FILTERS = ("", "in", "out")


def scope_messages() -> QuerySet[Message]:
    """The in-target channels' alive messages dated inside their in-target periods."""
    return (
        Message.objects.alive().filter(channel__in=Channel.objects.in_target().values("pk")).filter(channel_cutoff_q())
    )


def messages_with_emoji(messages: QuerySet[Message], emoji: CustomEmoji) -> QuerySet[Message]:
    """The messages of *messages* whose text draws *emoji* (each once, however many times it appears)."""
    return messages.filter(Exists(MessageCustomEmoji.objects.filter(message=OuterRef("pk"), emoji=emoji)))


def messages_touching(messages: QuerySet[Message], **emoji_filter: Any) -> QuerySet[Message]:
    """The messages of *messages* drawing, or reacted to with, the emoji *emoji_filter* matches
    (``emoji=…`` for one emoji, ``emoji__pack=…`` for a pack) — what a usage count reads."""
    spans = MessageCustomEmoji.objects.filter(message=OuterRef("pk"), **emoji_filter)
    reactions = MessageCustomReaction.objects.filter(message=OuterRef("pk"), **emoji_filter)
    return messages.filter(Exists(spans) | Exists(reactions))


def _empty_row(key: str, channel_id: int, value: int | None) -> dict[str, Any]:
    return {
        "channel_id": channel_id,
        key: value,
        "own_uses": 0,
        "own_messages": 0,
        "forwarded_uses": 0,
        "forwarded_messages": 0,
        "reactions": 0,
        "first_used": None,
        "last_used": None,
    }


def _widen(row: dict[str, Any], first: Any, last: Any) -> None:
    """Stretch *row*'s ``first_used`` / ``last_used`` span to cover ``[first, last]``."""
    if first is not None:
        row["first_used"] = first if row["first_used"] is None else min(row["first_used"], first)
    if last is not None:
        row["last_used"] = last if row["last_used"] is None else max(row["last_used"], last)


def usage_rows(messages: QuerySet[Message], level: str = "pack") -> list[dict[str, Any]]:
    """One row per (channel, pack or emoji) over *messages*: uses and messages in own posts and in
    forwards, custom-emoji reactions received, and the first / last date a post of the channel used it."""
    field = LEVELS[level]
    key = f"{level}_id"
    rows: dict[tuple[int, int | None], dict[str, Any]] = {}
    forwarded = Case(When(forward_header_q(), then=Value(True)), default=Value(False), output_field=BooleanField())
    uses = (
        messages.filter(custom_emoji_spans__isnull=False)
        .annotate(is_forward=forwarded)
        .values("channel_id", f"custom_emoji_spans__{field}", "is_forward")
        .annotate(uses=Count("custom_emoji_spans"), n=Count("id", distinct=True), first=Min("date"), last=Max("date"))
        .order_by()
    )
    for item in uses:
        group = (item["channel_id"], item[f"custom_emoji_spans__{field}"])
        row = rows.setdefault(group, _empty_row(key, *group))
        side = "forwarded" if item["is_forward"] else "own"
        row[f"{side}_uses"] += item["uses"]
        row[f"{side}_messages"] += item["n"]
        _widen(row, item["first"], item["last"])
    reactions = (
        messages.filter(custom_reactions__isnull=False)
        .values("channel_id", f"custom_reactions__{field}")
        .annotate(total=Sum("custom_reactions__count"))
        .order_by()
    )
    for item in reactions:
        group = (item["channel_id"], item[f"custom_reactions__{field}"])
        rows.setdefault(group, _empty_row(key, *group))["reactions"] += item["total"] or 0
    return list(rows.values())


def summaries(rows: list[dict[str, Any]], level: str = "pack") -> list[dict[str, Any]]:
    """Fold channel × pack (or emoji) *rows* into one summary per pack (or emoji), most widely used first.

    ``channels`` counts the channels that used it in their own posts; one seen only in forwards
    or reactions still gets a summary, with ``channels`` 0. The unresolved-pack summary sorts last.
    """
    key = f"{level}_id"
    folded: dict[int | None, dict[str, Any]] = {}
    for row in rows:
        summary = folded.setdefault(row[key], {**_empty_row(key, 0, row[key]), "channels": 0})
        summary["channels"] += 1 if row["own_uses"] else 0
        for field in ("own_uses", "own_messages", "forwarded_uses", "forwarded_messages", "reactions"):
            summary[field] += row[field]
        _widen(summary, row["first_used"], row["last_used"])
    for summary in folded.values():
        del summary["channel_id"]
    return sorted(
        folded.values(),
        key=lambda s: (s[key] is None, -s["channels"], -s["own_uses"], -s["reactions"], s[key] or 0),
    )


def pack_previews(messages: QuerySet[Message] | None, pack_ids: set[int]) -> dict[int, list[CustomEmoji]]:
    """Each pack's ``PREVIEW_SIZE`` most used emoji in *messages* — every stored post when ``None``
    (Manage → Emoji) — falling back to its first stored emoji for a pack seen only in reactions."""
    if not pack_ids:
        return {}
    spans = MessageCustomEmoji.objects.filter(emoji__pack_id__in=pack_ids)
    if messages is not None:
        spans = spans.filter(message__in=messages)
    counts = spans.values("emoji_id", "emoji__pack_id").annotate(n=Count("id")).order_by("-n", "emoji_id")
    chosen: dict[int, list[int]] = defaultdict(list)
    for item in counts:
        ids = chosen[item["emoji__pack_id"]]
        if len(ids) < PREVIEW_SIZE:
            ids.append(item["emoji_id"])
    # A pack seen only in reactions still gets a preview.
    for pack_id in pack_ids - set(chosen):
        chosen[pack_id] = list(
            CustomEmoji.objects.filter(pack_id=pack_id, is_unavailable=False)
            .exclude(file="")
            .order_by("pk")
            .values_list("pk", flat=True)[:PREVIEW_SIZE]
        )
    by_pk = CustomEmoji.objects.select_related("pack").in_bulk([pk for ids in chosen.values() for pk in ids])
    return {pack_id: [by_pk[pk] for pk in ids if pk in by_pk] for pack_id, ids in chosen.items()}


def monthly_own_uses(messages: QuerySet[Message], emoji: CustomEmoji) -> dict[str, list]:
    """*emoji*'s uses in own posts per calendar month, every month from the first use to the last
    included — ``{"labels": ["YYYY-MM", …], "values": [n, …]}``, the shape ``renderChart`` draws."""
    counts = {
        item["month"].strftime("%Y-%m"): item["n"]
        for item in MessageCustomEmoji.objects.filter(
            emoji=emoji, message__in=messages.exclude(forward_header_q()).filter(date__isnull=False)
        )
        .annotate(month=TruncMonth("message__date"))
        .values("month")
        .annotate(n=Count("id"))
        .order_by("month")
    }
    if not counts:
        return {"labels": [], "values": []}
    labels: list[str] = []
    year, month = (int(part) for part in min(counts).split("-"))
    last = max(counts)
    while True:
        label = datetime.date(year, month, 1).strftime("%Y-%m")
        labels.append(label)
        if label >= last:
            break
        year, month = (year + 1, 1) if month == 12 else (year, month + 1)
    return {"labels": labels, "values": [counts.get(label, 0) for label in labels]}


def attach_packs(items: list[dict[str, Any]]) -> None:
    """Set ``item["pack"]`` (``CustomEmojiPack`` or ``None``) on every item carrying a ``pack_id``."""
    packs = CustomEmojiPack.objects.prefetch_related("group_channels").in_bulk(
        {item["pack_id"] for item in items if item["pack_id"] is not None}
    )
    for item in items:
        item["pack"] = packs.get(item["pack_id"])


def attach_emoji(items: list[dict[str, Any]]) -> None:
    """Set ``item["emoji"]`` (pack selected) and ``item["pack"]`` on every item carrying an ``emoji_id``."""
    emoji = (
        CustomEmoji.objects.select_related("pack")
        .prefetch_related("pack__group_channels")
        .in_bulk({item["emoji_id"] for item in items})
    )
    for item in items:
        item["emoji"] = emoji.get(item["emoji_id"])
        item["pack"] = item["emoji"].pack if item["emoji"] is not None else None


def attach_channels(items: list[dict[str, Any]]) -> None:
    """Set ``item["channel"]`` on every item carrying a ``channel_id``, labels prefetched."""
    channels = Channel.objects.prefetch_related("channel_labels__label__group").in_bulk(
        {item["channel_id"] for item in items}
    )
    for item in items:
        item["channel"] = channels.get(item["channel_id"])


def target_filter(raw: str | None) -> str:
    """The ``?target=`` value, normalised to one of ``TARGET_FILTERS``."""
    return raw if raw in TARGET_FILTERS else ""


def in_target_only(items: list[dict[str, Any]], target: str) -> list[dict[str, Any]]:
    """*items* (each with its ``pack`` attached) kept by the ``target`` filter; an unresolved pack is out of target."""
    if not target:
        return items
    wanted = target == "in"
    return [item for item in items if bool(item["pack"] is not None and item["pack"].is_in_target) is wanted]
