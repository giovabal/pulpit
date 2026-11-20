"""Commenter accounts: who writes the replies in channels' discussion groups, and which of them the
audience statistics leave out.

A commenter is a *user account* behind a :class:`~webapp.models.MessageReply`: Telethon's marked
``sender_id`` is positive for a user and negative for a channel or group posting as itself (an
anonymous group admin, a channel persona), which is never a commenter.

Two kinds of account would distort any audience figure, so they are left out:

* **Telegram bots** — ``MessageReply.sender_is_bot``, Telegram's own ``User.bot``, captured as the
  replies are fetched.
* **Bulk posters** — an account with at least :data:`BULK_THREAD_COMMENTS` replies under a single
  post. On the corpus this was written for, no person wrote more than 40 under one post, while two
  accounts dumped 3,241 and 2,168 media replies into one archive thread — 29% of every stored reply.

Both flags are read across every stored reply, so an account's status does not change with the
scope of a page. The analyst's :class:`~webapp.models.CommenterReview` overrides them either way
(Manage → Commenters). Every audience figure goes through :func:`audience_replies`.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable

from django.db.models import Count, Max, Min, Q, QuerySet

from network.parameters import FixedParameter
from webapp.models import CommenterReview, MessageReply

BULK_THREAD_COMMENTS = 100

FIXED_PARAMETERS: tuple[FixedParameter, ...] = (
    FixedParameter(
        name="Commenters: bulk-poster threshold",
        value=BULK_THREAD_COMMENTS,
        scope="audience",
        affects="An account with at least this many replies under one post is left out of every audience figure "
        "(as is a Telegram bot), unless Manage → Commenters keeps it.",
        source="webapp/commenters.py: BULK_THREAD_COMMENTS",
    ),
)

REASON_TELEGRAM_BOT = "telegram_bot"
REASON_BULK = "bulk"
REASON_LABELS = {REASON_TELEGRAM_BOT: "Telegram bot", REASON_BULK: "Bulk poster"}

DECISION_AUTO = "auto"
DECISION_EXCLUDE = "exclude"
DECISION_KEEP = "keep"
DECISIONS = {None: DECISION_AUTO, True: DECISION_EXCLUDE, False: DECISION_KEEP}
DECISION_VALUES = {value: excluded for excluded, value in DECISIONS.items()}


def account_replies(replies: QuerySet | None = None) -> QuerySet:
    """*replies* (default: every stored reply) written by user accounts."""
    return (MessageReply.objects.all() if replies is None else replies).filter(sender_id__gt=0)


def automatic_flags(sender_ids: Iterable[int] | None = None) -> dict[int, list[str]]:
    """The automatic reasons to leave each flagged account out, read across every stored reply.

    *sender_ids* limits the check to those accounts; unflagged accounts are absent.
    """
    replies = account_replies()
    if sender_ids is not None:
        replies = replies.filter(sender_id__in=list(sender_ids))
    flags: dict[int, list[str]] = defaultdict(list)
    for sender_id in set(replies.filter(sender_is_bot=True).values_list("sender_id", flat=True)):
        flags[sender_id].append(REASON_TELEGRAM_BOT)
    bulk = (
        replies.values("sender_id", "parent_message")
        .annotate(n=Count("id"))
        .filter(n__gte=BULK_THREAD_COMMENTS)
        .values_list("sender_id", flat=True)
    )
    for sender_id in set(bulk):
        flags[sender_id].append(REASON_BULK)
    return dict(flags)


def excluded_sender_ids() -> set[int]:
    """The accounts the audience statistics leave out: flagged and not kept, or excluded by hand."""
    decisions = dict(CommenterReview.objects.filter(excluded__isnull=False).values_list("sender_id", "excluded"))
    flagged = {sender_id for sender_id in automatic_flags() if decisions.get(sender_id) is not False}
    return flagged | {sender_id for sender_id, excluded in decisions.items() if excluded}


def audience_replies(replies: QuerySet | None = None, excluded: set[int] | None = None) -> QuerySet:
    """*replies* written by user accounts the audience statistics keep."""
    if excluded is None:
        excluded = excluded_sender_ids()
    return account_replies(replies).exclude(sender_id__in=list(excluded))


def commenter_rows(sender_ids: Iterable[int] | None = None) -> list[dict]:
    """One row per commenter account over every stored reply, most active first (Manage → Commenters).

    ``name`` is one of the names the account replied under; ``max_per_post`` is its most replies under
    a single post, the bulk-poster test. ``telegram_bot`` is True / False, or None when no reply of the
    account has the flag captured yet.
    """
    if sender_ids is not None:
        sender_ids = list(sender_ids)
    replies = account_replies()
    if sender_ids is not None:
        replies = replies.filter(sender_id__in=sender_ids)
    per_post: dict[int, int] = defaultdict(int)
    for row in replies.values("sender_id", "parent_message").annotate(n=Count("id")):
        per_post[row["sender_id"]] = max(per_post[row["sender_id"]], row["n"])
    stats = replies.values("sender_id").annotate(
        name=Max("sender_name"),
        comments=Count("id"),
        no_text=Count("id", filter=Q(text="")),
        posts=Count("parent_message", distinct=True),
        channels=Count("parent_message__channel", distinct=True),
        bot_replies=Count("id", filter=Q(sender_is_bot=True)),
        captured=Count("id", filter=Q(sender_is_bot__isnull=False)),
        first=Min("date"),
        last=Max("date"),
    )
    reviews = {r.sender_id: r for r in CommenterReview.objects.filter(sender_id__in=[s["sender_id"] for s in stats])}
    flags = automatic_flags(sender_ids)
    rows = []
    for s in stats:
        sender_id = s["sender_id"]
        review = reviews.get(sender_id)
        decision = review.excluded if review else None
        reasons = flags.get(sender_id, [])
        rows.append(
            {
                "sender_id": sender_id,
                "name": s["name"] or "",
                "comments": s["comments"],
                "no_text_share": s["no_text"] / s["comments"],
                "posts": s["posts"],
                "channels": s["channels"],
                "max_per_post": per_post[sender_id],
                "telegram_bot": (s["bot_replies"] > 0) if s["captured"] else None,
                "first": s["first"].isoformat() if s["first"] else None,
                "last": s["last"].isoformat() if s["last"] else None,
                "reasons": [{"key": r, "label": REASON_LABELS[r]} for r in reasons],
                "decision": DECISIONS[decision],
                "excluded": decision if decision is not None else bool(reasons),
                "note": review.note if review else "",
            }
        )
    rows.sort(key=lambda row: (-row["comments"], row["sender_id"]))
    return rows


def set_review(sender_id: int, *, decision: str | None = None, note: str | None = None) -> None:
    """Record the analyst's *decision* (:data:`DECISION_VALUES` key) and/or *note* on an account.

    Only the fields given are written: the page sends the decision and the note separately, often a
    moment apart, and a whole-row save from the second request would write back the first one's field
    as it was before. A review back on automatic with no note is deleted: no row means "follow the
    flags".
    """
    fields: dict = {}
    if decision is not None:
        fields["excluded"] = DECISION_VALUES[decision]
    if note is not None:
        fields["note"] = note
    if not fields:
        return
    review, created = CommenterReview.objects.get_or_create(sender_id=sender_id, defaults=fields)
    if not created:
        for name, value in fields.items():
            setattr(review, name, value)
        review.save(update_fields=[*fields, "_updated"])
    CommenterReview.objects.filter(sender_id=sender_id, excluded__isnull=True, note="").delete()
