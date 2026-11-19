"""Channels found commenting as themselves, added to the channels list.

A reply's sender can be a channel or supergroup posting under its own name: ``MessageReply.sender_id``
is then the marked id −(10¹² + its Telegram id) (``webapp/audience/channel_commenters.py``). When no
crawl reached that channel, its name and id are all Pulpit holds — the Audience page can name it but
not link it, and a channel that has since closed leaves nothing else. This module discovers each
such channel and gives it a ``Channel`` row in the channels list:

* **at fetch time** — ``store_reply_sender`` stores the sender entity Telegram returns with the
  replies (a ``ChannelForbidden`` = our account cannot see it, stored as private);
* **for replies already stored** — ``recover_commenting_channels`` (command
  ``store_commenting_channels``) creates a placeholder from the reply's name and the Telethon
  session's entity cache (access hash, last handle seen), then asks Telegram through the crawler's
  own ``resolve_channel_or_classify``: live (row refreshed with the full details), private or lost.

Commenting under the post's own channel or from its discussion group is left out (the channel itself
or its anonymous admins), as on the Audience page. The rows are crawl- and graph-neutral: the crawl
scope is ever-in-target + ``to_inspect`` channels, and a comment is not a citation — a row enters an
export only when in-target messages cite it.
"""

from __future__ import annotations

import logging
import sqlite3
from collections import Counter, defaultdict
from collections.abc import Callable, Iterable
from contextlib import closing
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

from django.conf import settings

from webapp.models import Channel, MessageReply
from webapp.models.telegram_models import CHANNEL_PEER_MARK, channel_id_from_peer_id

from telethon.tl.types import Channel as TelegramChannel, ChannelForbidden

if TYPE_CHECKING:
    from crawler.channel_crawler import ChannelCrawler

logger = logging.getLogger(__name__)

#: Outcomes of ``recover_commenting_channels``, one per channel.
STATUS_LIVE = "live"
STATUS_PRIVATE = "private"
STATUS_LOST = "lost"
STATUS_USER_CLASH = "user_clash"


@dataclass(frozen=True)
class CommentingChannel:
    """A channel seen only as a reply's sender: its Telegram id, the name it commented under, how often."""

    telegram_id: int
    name: str
    comments: int


def _held_by_user_account(telegram_id: int) -> bool:
    """Whether a user-account row holds *telegram_id* — users and channels are separate id spaces that
    can coincide numerically, so the channel is not stored over it (``ReferenceResolver`` policy)."""
    if Channel.objects.filter(telegram_id=telegram_id, is_user_account=True).exists():
        logger.warning(
            "Commenting channel telegram_id=%s not stored: a user-account row holds the same id", telegram_id
        )
        return True
    return False


def unknown_commenting_channels() -> list[CommentingChannel]:
    """Every channel commenting as itself under another channel's stored posts with no channel row,
    most comments first. A user-account row holding the same id does not count as stored."""
    rows = MessageReply.objects.filter(sender_id__lt=-CHANNEL_PEER_MARK).values_list(
        "sender_id",
        "sender_name",
        "parent_message__channel__telegram_id",
        "parent_message__channel__linked_chat_id",
    )
    names: dict[int, Counter] = defaultdict(Counter)
    for sender_id, sender_name, channel_tid, linked_chat_id in rows.iterator(chunk_size=2000):
        tid = channel_id_from_peer_id(sender_id)
        if tid is None or tid == channel_tid or tid == linked_chat_id:
            continue
        names[tid][sender_name] += 1
    stored = set(
        Channel.objects.filter(telegram_id__in=names, is_user_account=False).values_list("telegram_id", flat=True)
    )
    found = [
        CommentingChannel(telegram_id=tid, name=counts.most_common(1)[0][0], comments=sum(counts.values()))
        for tid, counts in names.items()
        if tid not in stored
    ]
    found.sort(key=lambda c: (-c.comments, c.telegram_id))
    return found


def store_reply_sender(sender: Any, commented_on: Channel) -> Channel | None:
    """Store a reply's sender entity as a channel row when it is a channel commenting as itself under
    a post of another channel (*commented_on*) and no row holds its id yet. Returns the new row, else None."""
    if not isinstance(sender, TelegramChannel | ChannelForbidden):
        return None
    if sender.id in (commented_on.telegram_id, commented_on.linked_chat_id):
        return None
    if Channel.objects.filter(telegram_id=sender.id, is_user_account=False).exists():
        return None
    if _held_by_user_account(sender.id):
        return None
    channel = Channel.from_telegram_object(sender, force_update=True)
    if isinstance(sender, ChannelForbidden):
        Channel.objects.filter(pk=channel.pk).update(is_private=True, is_lost=False)
        channel.is_private = True
    logger.info("Commenting channel stored: %s [telegram_id=%s]", channel, channel.telegram_id)
    return channel


def session_path() -> Path:
    """The Telethon session file (Telethon appends ``.session`` to the configured name)."""
    name = settings.TELEGRAM_SESSION_NAME
    return Path(name if name.endswith(".session") else f"{name}.session")


def cached_entities(telegram_ids: Iterable[int], path: Path | None = None) -> dict[int, tuple[int | None, str]]:
    """``{telegram id: (access hash, last handle seen)}`` from the Telethon session's entity cache.

    Telethon caches every peer it receives — a commenter included — keyed by marked id, the handle
    lower-cased and empty when the channel had none (or was already gone) when last seen. Read through
    a read-only connection; a missing or unreadable session yields nothing.
    """
    path = path or session_path()
    marked = {-(CHANNEL_PEER_MARK + tid): tid for tid in telegram_ids}
    if not marked or not path.is_file():
        return {}
    try:
        with closing(sqlite3.connect(f"{path.resolve().as_uri()}?mode=ro", uri=True)) as db:
            rows = db.execute(
                f"SELECT id, hash, username FROM entities WHERE id IN ({','.join('?' * len(marked))})",  # noqa: S608
                list(marked),
            ).fetchall()
    except sqlite3.Error as exc:
        logger.warning("Could not read the Telethon session cache %s: %s", path, exc)
        return {}
    return {marked[peer_id]: (access_hash, username or "") for peer_id, access_hash, username in rows}


def _recover_one(crawler: ChannelCrawler, candidate: CommentingChannel, cached: tuple[int | None, str]) -> str:
    """Placeholder row, then Telegram's verdict on it (see ``recover_commenting_channels``)."""
    access_hash, username = cached
    placeholder, created = Channel.objects.get_or_create(
        telegram_id=candidate.telegram_id,
        is_user_account=False,
        defaults={"title": candidate.name[:255], "username": username, "access_hash": access_hash},
    )
    try:
        channel, telegram_channel, status = crawler.resolve_channel_or_classify(candidate.telegram_id)
        if status == "ok":
            crawler.media_handler.download_profile_picture(telegram_channel)
            crawler.set_more_channel_details(channel, telegram_channel)
            outcome = STATUS_LIVE
        elif status == "private":
            Channel.objects.filter(pk=placeholder.pk).update(is_private=True, is_lost=False)
            outcome = STATUS_PRIVATE
        else:
            # "lost", or "user_account": the id came from a channel's marked id, so a User answer is an
            # entity-cache collision between the two id spaces, not proof of a person.
            Channel.objects.filter(pk=placeholder.pk).update(is_lost=True, is_private=False)
            outcome = STATUS_LOST
    except BaseException:
        # No verdict (flood wait, network error): drop the placeholder so the next run retries it.
        if created:
            placeholder.delete()
        raise
    return outcome


def recover_commenting_channels(
    crawler: ChannelCrawler,
    candidates: Iterable[CommentingChannel] | None = None,
    report: Callable[[CommentingChannel, str], None] | None = None,
) -> dict[str, int]:
    """Give every unknown commenting channel a row and Telegram's verdict on it.

    Each gets a placeholder (the name it commented under, the session's cached access hash and handle)
    so ``resolve_channel_or_classify`` can run its whole fallback chain, then: live → refreshed from
    Telegram with profile picture and full details (``refresh_channel_info``'s steps); private →
    ``is_private``; lost → ``is_lost``. ``FloodWaitError``
    and other failures propagate after the channel's placeholder is removed. Returns the count per
    outcome; *report* is called once per channel.
    """
    candidates = list(unknown_commenting_channels() if candidates is None else candidates)
    cache = cached_entities(c.telegram_id for c in candidates)
    counts: Counter = Counter()
    for candidate in candidates:
        if _held_by_user_account(candidate.telegram_id):
            outcome = STATUS_USER_CLASH
        else:
            outcome = _recover_one(crawler, candidate, cache.get(candidate.telegram_id, (None, "")))
        counts[outcome] += 1
        if report is not None:
            report(candidate, outcome)
    return dict(counts)
