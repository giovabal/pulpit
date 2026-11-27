"""Record the @handles of stored posts as mentions (``backfill_mentions``).

The crawler reads @handles as it stores a message (``reference_resolver.message_references``); this does
the same for the posts stored before it did, from their text alone. Scope: the posts the analysis counts,
in-target channels within their in-target periods (``channel_cutoff_q``) — the rest of the database can hold
tens of thousands of unknown handles nothing reads.

Two steps. ``plan_backfill`` + ``apply_plan`` need no Telegram: handles of stored channels and bots become
references, unknown ones are queued in ``missing_references`` as a crawl would leave them.
``look_up_handles`` then asks Telegram about the unknown ones, once per handle, the most used first. It
settles each handle as it goes, so a flood wait loses nothing and the next run carries on.
"""

from collections import Counter, defaultdict
from collections.abc import Callable
from dataclasses import dataclass, field

from django.db import transaction

from crawler.reference_resolver import (
    DEAD_PREFIX,
    MENTION_PREFIX,
    ReferenceResolver,
    add_references,
    is_signature,
    message_references,
)
from network.utils import channel_cutoff_q
from webapp.models import Channel, Message

#: Messages handled per transaction.
BATCH_SIZE = 500

FOUND = "found"
DROPPED = "dropped"


@dataclass
class BackfillPlan:
    """What the stored posts' @handles amount to; nothing written."""

    posts: int = 0  # in-scope posts carrying at least one @handle
    references: list[tuple[int, int]] = field(default_factory=list)  # (message pk, channel pk), new ones only
    unknown: dict[str, list[int]] = field(default_factory=dict)  # handle -> pks of the messages naming it
    skipped: Counter = field(default_factory=Counter)  # mentions left out, by reason

    def unknown_by_use(self) -> list[tuple[str, list[int]]]:
        return sorted(self.unknown.items(), key=lambda item: (-len(item[1]), item[0]))


def _known_handles() -> dict[str, tuple[int, bool]]:
    """Handle -> (channel pk, is a person). Same preference as ``ReferenceResolver._resolve_one``."""
    known: dict[str, tuple[int, bool]] = {}
    rows = Channel.objects.with_a_handle().order_by("is_lost", "pk")
    fields = ("pk", "username", "extra_usernames", "is_user_account", "is_bot")
    for pk, username, extra_usernames, is_user, is_bot in rows.values_list(*fields):
        for handle in Channel.handles_of(username, extra_usernames):
            known.setdefault(handle, (pk, is_user and not is_bot))
    return known


def _without_stored(pairs: list[tuple[int, int]]) -> list[tuple[int, int]]:
    """*pairs* minus the references already in the database."""
    through = Message.references.through
    message_pks = sorted({message_pk for message_pk, _ in pairs})
    stored: set[tuple[int, int]] = set()
    for start in range(0, len(message_pks), BATCH_SIZE):
        chunk = message_pks[start : start + BATCH_SIZE]
        stored.update(through.objects.filter(message_id__in=chunk).values_list("message_id", "channel_id"))
    return [pair for pair in pairs if pair not in stored]


def plan_backfill() -> BackfillPlan:
    """Read the in-scope posts and sort their @handles into references to add and handles to look up."""
    known = _known_handles()
    plan = BackfillPlan()
    unknown: dict[str, list[int]] = defaultdict(list)
    pairs: list[tuple[int, int]] = []
    posts = (
        Message.objects.filter(channel_cutoff_q(), message__contains=MENTION_PREFIX)
        .values_list("pk", "channel_id", "forwarded_from_id", "message", "missing_references")
        .iterator(chunk_size=2000)
    )
    for pk, channel_pk, forwarded_from_pk, text, missing in posts:
        mentions = [ref for ref in message_references(text, None) if ref.startswith(MENTION_PREFIX)]
        plan.posts += bool(mentions)
        dead = {raw for raw in (missing or "").split("|") if raw.startswith(DEAD_PREFIX)}
        for reference in mentions:
            handle = reference.removeprefix(MENTION_PREFIX)
            if handle in known:
                cited_pk, is_person = known[handle]
                if is_person:
                    plan.skipped["people"] += 1
                elif is_signature(reference, cited_pk, channel_pk, forwarded_from_pk):
                    plan.skipped["signatures"] += 1
                else:
                    pairs.append((pk, cited_pk))
            elif DEAD_PREFIX + reference in dead:
                plan.skipped["looked up before"] += 1
            else:
                unknown[handle].append(pk)
    plan.references = _without_stored(pairs)
    plan.skipped["already stored"] = len(pairs) - len(plan.references)
    plan.unknown = dict(unknown)
    return plan


def _rewrite_missing(message_pks: list[int], change: Callable[[list[str], int], list[str]]) -> None:
    """Apply *change* to the ``missing_references`` entries of each message."""
    messages = list(Message.objects.filter(pk__in=message_pks).only("pk", "missing_references"))
    changed = []
    for message in messages:
        entries = [raw for raw in message.missing_references.split("|") if raw]
        new_value = "|".join(change(entries, message.pk))
        if new_value != message.missing_references:
            message.missing_references = new_value
            changed.append(message)
    Message.objects.bulk_update(changed, ["missing_references"])


def apply_plan(plan: BackfillPlan) -> None:
    """Write the plan's references and queue its unknown handles. No Telegram call; safe to repeat."""
    for start in range(0, len(plan.references), BATCH_SIZE):
        add_references(plan.references[start : start + BATCH_SIZE])
    queued: dict[int, list[str]] = defaultdict(list)
    for handle, message_pks in plan.unknown.items():
        for pk in message_pks:
            queued[pk].append(MENTION_PREFIX + handle)
    pks = sorted(queued)
    for start in range(0, len(pks), BATCH_SIZE):
        with transaction.atomic():
            _rewrite_missing(
                pks[start : start + BATCH_SIZE],
                lambda entries, pk: entries + [ref for ref in sorted(queued[pk]) if ref not in entries],
            )


def _settle(reference: str, message_pks: list[int], channel: Channel | None) -> int:
    """Record a looked-up handle on its messages; returns the references added."""
    dead = [] if channel is not None else [DEAD_PREFIX + reference]
    added = 0
    for start in range(0, len(message_pks), BATCH_SIZE):
        chunk = message_pks[start : start + BATCH_SIZE]
        with transaction.atomic():
            if channel is not None:
                owners = Message.objects.filter(pk__in=chunk).values_list("pk", "channel_id", "forwarded_from_id")
                pairs = [
                    (pk, channel.pk) for pk, own, fwd in owners if not is_signature(reference, channel.pk, own, fwd)
                ]
                pairs = _without_stored(pairs)
                add_references(pairs)
                added += len(pairs)
            _rewrite_missing(chunk, lambda entries, _pk: [raw for raw in entries if raw != reference] + dead)
    return added


def look_up_handles(
    resolver: ReferenceResolver,
    plan: BackfillPlan,
    limit: int | None = None,
    report: Callable[[str, int, Channel | None, str], None] | None = None,
) -> Counter:
    """Ask Telegram about the plan's unknown handles, the most used first.

    Returns the handles ``found`` / ``dropped`` (nothing there, or a person) / ``left`` for a later run and the
    ``references`` added. Stops at a flood wait long enough to pause the resolver; what is left stays queued.
    """
    counts: Counter = Counter()
    handles = plan.unknown_by_use()
    for done, (handle, message_pks) in enumerate(handles):
        if resolver.is_paused() or (limit is not None and done >= limit):
            counts["left"] += len(handles) - done
            break
        reference = MENTION_PREFIX + handle
        channel, should_retry = resolver._resolve_one(reference)
        if should_retry:
            counts["left"] += 1
            continue
        counts["references"] += _settle(reference, message_pks, channel)
        outcome = FOUND if channel is not None else DROPPED
        counts[outcome] += 1
        if report is not None:
            report(handle, len(message_pks), channel, outcome)
    return counts
