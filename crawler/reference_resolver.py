import logging
import re
from collections.abc import Callable, Iterable
from datetime import datetime, timedelta
from typing import Any

from django.db import transaction
from django.utils import timezone

from crawler.client import TelegramAPIClient
from webapp.models import Channel, Message

from telethon import errors
from telethon.tl.types import User

logger = logging.getLogger(__name__)

# First path segments of t.me links that never name a public channel: Telegram reserves them for
# invite links ("joinchat"), sticker/emoji sets, folder links, proxies, Instant View, login and
# phone-confirmation codes, language packs, themes, wallpapers, invoices, business chat links,
# contact tokens, gift codes, and t.me/c/<id>/<post> private-message links (which name a channel
# only by its bare numeric id — no username to resolve, so they have never produced a citation).
# "s" (t.me/s/<username> web preview) and "boost" (t.me/boost/<username>) are prefixes in front of
# the real handle and are stripped by ``reference_from_path``; listed here so a bare one (or one
# stored by an older parser) is never sent to get_entity. Imported by crawl_channels for the
# about-text mining as well.
SKIPPABLE_REFERENCES = frozenset(
    {
        "joinchat",
        "addlist",
        "addstickers",
        "addemoji",
        "addtheme",
        "bg",
        "boost",
        "c",
        "confirmphone",
        "contact",
        "giftcode",
        "invoice",
        "iv",
        "login",
        "m",
        "proxy",
        "s",
        "setlanguage",
        "share",
        "socks",
    }
)
# Path prefixes that stand in front of the channel's handle: t.me/s/<username> (web preview) and
# t.me/boost/<username> (boost link — the same channel as t.me/<username>?boost).
_HANDLE_PREFIXES = frozenset({"s", "boost"})

# A t.me link in any spelling: scheme, "www." and host case are optional / insensitive, and
# telegram.me is the legacy alias of t.me.
_TME_HOST = r"(?:https?://)?(?:www\.)?(?:t|telegram)\.me/"
_TME_URL_RE = re.compile(rf"^{_TME_HOST}(?P<path>.*)$", re.IGNORECASE | re.DOTALL)
# Plain-text links: \w only for the handle — Telegram usernames are [A-Za-z0-9_], so accepting "."
# or "-" would swallow trailing sentence punctuation ("t.me/canale." → "canale.") and the resolver
# would classify the mangled handle as a permanent failure. The look-behind keeps "t.me/" inside an
# unrelated host ("chat.me/…") from reading as a Telegram link.
_HANDLE = r"(?:\w|%[\da-fA-F]{2})+"
_TME_TEXT_RE = re.compile(
    rf"(?<![\w.\-]){_TME_HOST}(?P<path>(?:(?:s|boost)/)?[+$]?{_HANDLE})",
    re.IGNORECASE,
)

# Prefix stored in missing_references to mark a reference as permanently unresolvable.
# Prefixed entries are skipped on subsequent retries unless force_retry=True.
DEAD_PREFIX = "!"


def reference_from_path(path: str) -> str | None:
    """The lower-cased channel handle a t.me path names, or ``None`` when it names none.

    ``path`` is everything after ``t.me/``: the query string and fragment are dropped
    ("chan?boost", "chan#x"), a ``s/`` or ``boost/`` prefix is skipped, and the first
    remaining segment is the handle ("chan/123" → "chan"). Invite links (``joinchat``,
    ``+hash``), invoice slugs (``$slug``) and the reserved paths in
    ``SKIPPABLE_REFERENCES`` yield ``None``.
    """
    path = path.split("?", 1)[0].split("#", 1)[0]
    segments = [segment.strip().lower() for segment in path.split("/") if segment.strip()]
    if segments and segments[0] in _HANDLE_PREFIXES:
        segments = segments[1:]
    if not segments:
        return None
    handle = segments[0]
    if handle.startswith(("+", "$")) or handle in SKIPPABLE_REFERENCES:
        return None
    return handle


def reference_from_url(url: str) -> str | None:
    """The channel handle a link-entity URL names, or ``None`` for a non-t.me / non-channel link."""
    match = _TME_URL_RE.match(url.strip())
    return reference_from_path(match.group("path")) if match else None


def extract_text_references(text: str) -> list[str]:
    """Channel handles named by t.me links in a message's plain text, in order (duplicates kept)."""
    refs = (reference_from_path(match.group("path")) for match in _TME_TEXT_RE.finditer(text or ""))
    return [ref for ref in refs if ref]


def message_references(text: str | None, entities: Iterable[Any] | None) -> set[str]:
    """Channel handles a message names: t.me links in its text plus link-entity URLs."""
    refs = set(extract_text_references(text or ""))
    for entity in entities or ():
        url = getattr(entity, "url", None)
        if isinstance(url, str) and (ref := reference_from_url(url)):
            refs.add(ref)
    return refs


def _bulk_add_references(pairs: list[tuple["Message", "Channel"]]) -> None:
    """Insert M2M references in a single bulk_create instead of one query per pair."""
    if not pairs:
        return
    through = Message.references.through
    through.objects.bulk_create(
        [through(message_id=msg.pk, channel_id=ch.pk) for msg, ch in pairs],
        ignore_conflicts=True,
    )


class ReferenceResolver:
    def __init__(self, api_client: TelegramAPIClient) -> None:
        self.api_client = api_client
        self.reference_resolution_paused_until: datetime | None = None

    def _is_paused(self) -> bool:
        return bool(self.reference_resolution_paused_until and timezone.now() < self.reference_resolution_paused_until)

    def _pause(self, error: Any) -> int:
        wait_seconds = max(getattr(error, "seconds", 0), 1)
        pause_until = timezone.now() + timedelta(seconds=wait_seconds)
        if not self.reference_resolution_paused_until or pause_until > self.reference_resolution_paused_until:
            self.reference_resolution_paused_until = pause_until
        return wait_seconds

    @staticmethod
    def _user_account_channel(user: User, reference: str) -> Channel | None:
        """Store the target of a t.me/<user or bot> link as a user-account row.

        ``Channel.from_telegram_object`` would build the row from the User's fields and
        leave ``broadcast`` at its default, typing a bot or person as a CHANNEL that passes
        the default ``--channel-types CHANNEL`` filter and turns into an untitled dead-leaf
        node. Marked ``is_user_account`` (the USER bucket, like the crawler's own
        "user_account" verdicts) instead, the reference still attaches — a USER-inclusive
        analysis sees the citation, a channel-only one filters it out — and the stored
        handle short-circuits the next lookup instead of calling get_entity again. Only the
        handle is kept, no personal fields.

        User and channel ids are separate Telegram namespaces that can coincide
        numerically, so a stored non-user row already holding this id is left untouched
        and the reference dropped (``None``) rather than overwritten.
        """
        clash = Channel.objects.filter(telegram_id=user.id, is_user_account=False).first()
        if clash is not None:
            logger.warning(
                "Reference '%s' resolves to user account id=%s, which a stored channel (%s) also holds; "
                "not recording it",
                reference,
                user.id,
                clash,
            )
            return None
        channel, _ = Channel.objects.update_or_create(
            telegram_id=user.id,
            defaults={"username": user.username or reference, "is_user_account": True, "broadcast": False},
        )
        return channel

    def _resolve_one(self, reference: str, log_prefix: str = "") -> tuple[Channel | None, bool]:
        """Try to resolve a username to a Channel.

        Returns (channel, should_retry) where:
          - (channel, False) — resolved successfully
          - (None, True)     — temporary failure (flood wait, RPC error, paused); retry later
          - (None, False)    — permanent failure (username invalid or not found); do not retry
        """
        # Username is NOT a unique identity: Telegram handles get recycled, so the same
        # username can be held by several rows — a now-lost old channel and the live
        # channel that took over the handle. Prefer a live (non-lost) row, i.e. the
        # current owner, over a stale/lost one that merely used to hold it; fall back to
        # a lost row only when the handle has no live owner stored.
        # iexact: references are lowercased upstream, but Channel.username stores
        # Telegram's display casing ("ANPI_Roma"), and `=` is case-sensitive on both
        # SQLite and PostgreSQL — an exact match would always miss mixed-case handles
        # and fall through to a (flood-wait-prone, and for dead channels permanently
        # failing) get_entity call.
        channel = Channel.objects.filter(username__iexact=reference).order_by("is_lost", "pk").first()
        if channel:
            return channel, False

        if self._is_paused():
            return None, True

        try:
            self.api_client.wait()
            new_telegram_channel = self.api_client.client.get_entity(reference)
            if isinstance(new_telegram_channel, User):
                return self._user_account_channel(new_telegram_channel, reference), False
            return Channel.from_telegram_object(new_telegram_channel, force_update=True), False
        except (ValueError, errors.rpcerrorlist.UsernameInvalidError):
            # Permanent: username does not exist or is invalid — no point retrying
            return None, False
        except errors.rpcerrorlist.FloodWaitError as error:
            wait_seconds = self._pause(error)
            logger.warning(
                "Unable to resolve %sreference '%s' due to flood wait (%ss); skipping for now",
                f"{log_prefix} " if log_prefix else "",
                reference,
                wait_seconds,
            )
            return None, True
        except errors.RPCError as error:
            # Transient RPC error — keep for retry
            logger.warning(
                "Unable to resolve %sreference '%s': %s",
                f"{log_prefix} " if log_prefix else "",
                reference,
                error,
            )
            return None, True

    def resolve_message_references(self, message: Message, telegram_message: Any) -> list[str]:
        """Resolve all references in a message. Returns list of unresolved reference strings."""
        missing: list[str] = []
        for reference in message_references(message.message, telegram_message.entities):
            channel, should_retry = self._resolve_one(reference)
            if channel:
                message.references.add(channel)
            elif should_retry:
                missing.append(reference)

        return missing

    def get_missing_references(
        self,
        status_callback: Callable[[str], None] | None = None,
        force_retry: bool = False,
        channel_qs=None,
    ) -> None:
        qs = Message.objects.exclude(missing_references="")
        if channel_qs is not None:
            qs = qs.filter(channel__in=channel_qs)
        total = qs.count() if status_callback is not None else 0
        to_update: list[Message] = []
        to_add: list[tuple[Message, "Channel"]] = []
        for index, message in enumerate(qs.iterator(chunk_size=500), start=1):
            remaining: list[str] = []
            for raw in message.missing_references.split("|"):
                if not raw:
                    continue
                is_dead = raw.startswith(DEAD_PREFIX)
                stored = raw[len(DEAD_PREFIX) :] if is_dead else raw
                # Older parsers stored link-entity paths verbatim ("chan?boost", "chan#x") and the
                # bare prefix of /s/ previews: normalise like a fresh parse. A dead verdict on a
                # spelling that normalises to a different handle was about the mangled string,
                # not the channel, so that handle is retried once.
                reference = reference_from_path(stored)
                if reference is None:
                    continue
                if reference != stored:
                    is_dead = False
                if is_dead and not force_retry:
                    remaining.append(raw)
                    continue
                channel, should_retry = self._resolve_one(reference)
                if channel:
                    to_add.append((message, channel))  # deferred until after bulk_update
                elif should_retry:
                    remaining.append(reference)  # transient failure — keep for retry
                else:
                    remaining.append(DEAD_PREFIX + reference)  # permanent failure — mark dead
            new_value = "|".join(remaining)
            if new_value != message.missing_references:
                message.missing_references = new_value
                to_update.append(message)
            if len(to_update) >= 500:
                # bulk_update and bulk_add together: if the M2M create fails
                # after the missing_references string is shortened, the
                # message ends up with no record of the resolved references
                # and no entry in missing_references to retry.
                with transaction.atomic():
                    Message.objects.bulk_update(to_update, ["missing_references"])
                    _bulk_add_references(to_add)
                to_update.clear()
                to_add.clear()
            if status_callback is not None:
                status_callback(f"{index}/{total}")
        if to_update or to_add:
            with transaction.atomic():
                if to_update:
                    Message.objects.bulk_update(to_update, ["missing_references"])
                _bulk_add_references(to_add)
