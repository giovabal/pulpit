"""Channels commenting as themselves (``/audience/channel-commenters/``).

A reply's sender can be a channel or group instead of a person: Telethon's marked id is then negative,
−(10¹² + the channel's Telegram id). Three cases, told apart by that id:

* **Own posts** — a channel answering under its own posts, as itself.
* **Discussion group** — the post's own discussion group: its anonymous admins.
* **Another channel** — a channel commenting, under its own name, on another channel's posts. That is a
  channel-to-channel tie the citation graph does not see (it is built from forwards and mentions), so
  each pair says whether the two channels also forward or mention each other, either way, in any of
  their stored messages.

Channels are public actors, so they are named here (unlike the people commenting).
"""

from __future__ import annotations

from collections import Counter, defaultdict

from django.db.models import Q

from webapp.models import Channel, Label, Message, MessageReply

from .scope import coverage, scope_posts

#: Telethon marks a channel's id as −(MARKED_CHANNEL_OFFSET + id).
MARKED_CHANNEL_OFFSET = 1_000_000_000_000

KIND_OWN = "own"
KIND_GROUP = "group"
KIND_OTHER = "other"


def channel_telegram_id(sender_id: int) -> int | None:
    """The Telegram id of the channel behind a marked *sender_id*, or None for a person or a basic group."""
    if sender_id is None or sender_id >= 0 or -sender_id <= MARKED_CHANNEL_OFFSET:
        return None
    return -sender_id - MARKED_CHANNEL_OFFSET


def _cited(a: Channel, b: Channel) -> bool:
    """Whether either channel forwards or mentions the other in a stored, alive message."""
    messages = Message.objects.alive()
    forwards = messages.filter(Q(channel=a, forwarded_from=b) | Q(channel=b, forwarded_from=a)).exists()
    if forwards:
        return True
    return Message.references.through.objects.filter(
        Q(message__channel=a, channel=b) | Q(message__channel=b, channel=a), message__is_lost=False
    ).exists()


def channel_commenters(voice: Label | None = None) -> dict:
    """Everything the channels-as-commenters section shows, for one scope."""
    rows = MessageReply.objects.filter(parent_message__in=scope_posts(voice).values("pk"), sender_id__lt=0).values_list(
        "sender_id",
        "sender_name",
        "date",
        "parent_message__channel_id",
        "parent_message__channel__telegram_id",
        "parent_message__channel__linked_chat_id",
    )
    kinds: Counter = Counter()
    pairs: dict[tuple[int, int], dict] = {}
    names: dict[int, Counter] = defaultdict(Counter)
    for sender_id, sender_name, date, channel_id, channel_tid, linked_chat in rows:
        tid = channel_telegram_id(sender_id)
        if tid is None:
            continue
        if tid == channel_tid:
            kinds[KIND_OWN] += 1
            continue
        if linked_chat is not None and tid == linked_chat:
            kinds[KIND_GROUP] += 1
            continue
        kinds[KIND_OTHER] += 1
        names[tid][sender_name] += 1
        pair = pairs.setdefault((tid, channel_id), {"comments": 0, "first": date, "last": date})
        pair["comments"] += 1
        if date is not None:
            pair["first"] = min(d for d in (pair["first"], date) if d is not None)
            pair["last"] = max(d for d in (pair["last"], date) if d is not None)
    known = {c.telegram_id: c for c in Channel.objects.filter(telegram_id__in={tid for tid, _ in pairs})}
    commented = Channel.objects.in_bulk([ch for _, ch in pairs])
    out = []
    for (tid, channel_id), info in pairs.items():
        sender = known.get(tid)
        target = commented.get(channel_id)
        out.append(
            {
                **info,
                "sender": sender,
                "sender_tid": tid,
                "sender_name": names[tid].most_common(1)[0][0] if names[tid] else "",
                "sender_in_target": bool(sender and sender.is_in_target),
                "channel": target,
                "cited": _cited(sender, target) if sender and target else None,
            }
        )
    out.sort(key=lambda r: (-r["comments"], r["sender_tid"], r["channel"].pk if r["channel"] else 0))
    return {
        "pairs": out,
        "kinds": {KIND_OWN: kinds[KIND_OWN], KIND_GROUP: kinds[KIND_GROUP], KIND_OTHER: kinds[KIND_OTHER]},
        "commenting_channels": len({tid for tid, _ in pairs}),
        "uncited_pairs": sum(1 for r in out if r["cited"] is False),
        **coverage(voice),
    }
