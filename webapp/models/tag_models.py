import unicodedata
from collections import defaultdict
from collections.abc import Iterable
from functools import reduce
from itertools import batched
from operator import or_
from typing import Any

from django.conf import settings
from django.db import models, transaction
from django.db.models import Q

from webapp.models.base import BaseColorModel, BaseModel
from webapp.models.telegram_models import Channel, Message

from colorfield.fields import ColorField

# d3's category10 colours, then their lighter category20 companions: twenty
# well-known, mutually distinct hues that read as chip backgrounds in both
# themes (chip text flips black/white via ``is_color_dark``). New tags take the
# first colour no existing tag uses (``next_tag_color``).
TAG_PALETTE: tuple[str, ...] = (
    "#1f77b4",
    "#ff7f0e",
    "#2ca02c",
    "#d62728",
    "#9467bd",
    "#8c564b",
    "#e377c2",
    "#7f7f7f",
    "#bcbd22",
    "#17becf",
    "#aec7e8",
    "#ffbb78",
    "#98df8a",
    "#ff9896",
    "#c5b0d5",
    "#c49c94",
    "#f7b6d2",
    "#c7c7c7",
    "#dbdb8d",
    "#9edae5",
)


def next_tag_color() -> str:
    """The first ``TAG_PALETTE`` colour no tag uses yet, cycling once all are taken.

    Used as the field default, so a tag created on the fly from a post card
    gets a colour distinct from its siblings without the analyst picking one.
    """
    used = {c.lower() for c in MessageTag.objects.values_list("color", flat=True)}
    for color in TAG_PALETTE:
        if color not in used:
            return color
    return TAG_PALETTE[MessageTag.objects.count() % len(TAG_PALETTE)]


def normalize_tag_name(raw: str) -> str:
    """Trim and collapse internal whitespace: ``"  key   event "`` → ``"key event"``."""
    return " ".join((raw or "").split())


def tag_key(name: str) -> str:
    """Case- and width-insensitive identity of a tag name (NFKC + casefold).

    Stored on :attr:`MessageTag.key` with a unique index: SQLite's ``LOWER`` /
    ``iexact`` only fold ASCII, which would let "Война" and "война" coexist.
    """
    return unicodedata.normalize("NFKC", normalize_tag_name(name)).casefold()


class MessageTag(BaseColorModel):
    """An informal, analyst-defined tag for retrieving messages later.

    Deliberately separate from :class:`~webapp.models.Label`: tags are free-form
    bookmarks on posts, created on the fly, with no groups, periods, or in-target
    semantics, and no effect on the graph pipeline. A tag put on a post reaches
    the original and every share of it (:class:`MessageTagging`). The tag set is
    shared by the whole team; each tagging records who applied it.
    """

    name = models.CharField(max_length=64)
    key = models.CharField(max_length=64, unique=True, editable=False)
    description = models.TextField(blank=True, default="")
    color = ColorField(default=next_tag_color)

    class Meta:
        ordering = ["key"]

    def __str__(self) -> str:
        return self.name

    def save(self, *args, **kwargs) -> None:
        self.name = normalize_tag_name(self.name)
        self.key = tag_key(self.name)
        super().save(*args, **kwargs)

    def merge_into(self, target: "MessageTag") -> int:
        """Move this tag's posts onto ``target``, then delete this tag.

        A post already carrying ``target`` keeps that tagging; its note is filled
        from this tag's tagging only when it was empty. Returns the number of
        messages that gained ``target``.
        """
        if target.pk == self.pk:
            raise ValueError("Cannot merge a tag into itself.")
        with transaction.atomic():
            before = TaggedMessage.objects.filter(tagging__tag=target).values("message_id").distinct().count()
            existing = {t.origin: t for t in target.taggings.all()}
            moved: list[MessageTagging] = []
            for tagging in self.taggings.all():
                kept = existing.get(tagging.origin)
                if kept is None:
                    tagging.tag = target
                    tagging.save(update_fields=["tag", "_updated"])
                    moved.append(tagging)
                elif tagging.note and not kept.note:
                    kept.note = tagging.note
                    kept.save(update_fields=["note", "_updated"])
            self.delete()
            sync_tag_members(moved)
            after = TaggedMessage.objects.filter(tagging__tag=target).values("message_id").distinct().count()
        return after - before


def message_origin(message: Message) -> tuple[int, int]:
    """The Telegram ``(channel id, post id)`` of the post ``message`` is — or shares.

    Telegram's forward header names the first publication even when a share is
    itself re-shared, so a post and every forward of it resolve to one origin.
    A forward whose origin post id is unknown counts as a post of its own. The
    origin channel is the resolved ``forwarded_from``, else the raw id of a
    private channel, else the id still awaiting resolution (mid-crawl, or left
    pending across runs when the deferred lookup failed) — the same id the
    crawler reads from the forward header (``crawler.channel_crawler``).
    Reads ``channel`` and ``forwarded_from``: select them with the message.
    """
    if message.fwd_from_channel_post is not None:
        if message.forwarded_from_id is not None:
            return message.forwarded_from.telegram_id, message.fwd_from_channel_post
        if message.forwarded_from_private is not None:
            return message.forwarded_from_private, message.fwd_from_channel_post
        if message.pending_forward_telegram_id is not None:
            return message.pending_forward_telegram_id, message.fwd_from_channel_post
    return message.channel.telegram_id, message.telegram_id


# Origins per query when resolving members: each adds up to two OR terms, which
# keeps the statement well under SQLite's expression-depth limit (1000).
_ORIGIN_CHUNK = 150


def resolve_origin_messages(origins: Iterable[tuple[int, int]]) -> dict[tuple[int, int], set[int]]:
    """Message pks per origin: the original post (when stored) plus every share of it.

    Driven from the (few) origins rather than the (millions of) messages: each
    origin is a pair of indexed seeks on ``channel_id`` / ``forwarded_from_id``,
    and shares of a post from a private, unresolved channel come from the partial
    ``webapp_msg_fwd_private_idx`` on ``(forwarded_from_private, fwd_from_channel_post)``.
    Shares whose source is still awaiting resolution (``pending_forward_telegram_id``
    — ``message_origin``'s third case, which persists across runs when the deferred
    lookup keeps failing) come from one pass over the pending rows: they are few
    and transient, read through the partial ``webapp_msg_fwd_pending_idx``.
    """
    origins = set(origins)
    found: dict[tuple[int, int], set[int]] = defaultdict(set)
    if not origins:
        return found
    tid_by_pk = dict(
        Channel.objects.filter(telegram_id__in={tid for tid, _ in origins}).values_list("pk", "telegram_id")
    )
    pks_by_tid: dict[int, list[int]] = defaultdict(list)
    for pk, tid in tid_by_pk.items():
        pks_by_tid[tid].append(pk)
    for chunk in batched(sorted(origins), _ORIGIN_CHUNK):
        wanted = set(chunk)
        terms = [
            Q(channel_id=pk, telegram_id=post) | Q(forwarded_from_id=pk, fwd_from_channel_post=post)
            for tid, post in chunk
            for pk in pks_by_tid.get(tid, ())
        ]
        if terms:
            rows = Message.objects.filter(reduce(or_, terms)).values_list(
                "pk", "channel_id", "telegram_id", "forwarded_from_id", "fwd_from_channel_post"
            )
            for pk, channel_id, telegram_id, fwd_id, fwd_post in rows:
                for origin in ((tid_by_pk.get(channel_id), telegram_id), (tid_by_pk.get(fwd_id), fwd_post)):
                    if origin in wanted:
                        found[origin].add(pk)
        private = Message.objects.filter(
            forwarded_from_private__isnull=False,
            forwarded_from_private__in={tid for tid, _ in chunk},
            fwd_from_channel_post__in={post for _, post in chunk},
        ).values_list("pk", "forwarded_from_private", "fwd_from_channel_post")
        for pk, tid, post in private:
            if (tid, post) in wanted:
                found[(tid, post)].add(pk)
    pending = Message.objects.filter(
        pending_forward_telegram_id__isnull=False, fwd_from_channel_post__isnull=False
    ).values_list("pk", "pending_forward_telegram_id", "fwd_from_channel_post")
    for pk, tid, post in pending.iterator(chunk_size=2000):
        if (tid, post) in origins:
            found[(tid, post)].add(pk)
    return found


def link_stored_message(message_pk: int, origin: tuple[int, int]) -> int:
    """Give a just-stored message the tags of its post; returns links added.

    The crawler calls this for every message it stores, so a share (or an
    original) fetched after its post was tagged carries the tag at once. One
    indexed lookup on the small taggings table; idempotent on re-fetches.
    """
    tagging_ids = list(
        MessageTagging.objects.filter(origin_channel_tid=origin[0], origin_post_tid=origin[1]).values_list(
            "pk", flat=True
        )
    )
    if tagging_ids:
        TaggedMessage.objects.bulk_create(
            [TaggedMessage(tagging_id=pk, message_id=message_pk) for pk in tagging_ids], ignore_conflicts=True
        )
    return len(tagging_ids)


def sync_tag_members(taggings: Iterable["MessageTagging"] | None = None) -> int:
    """Attach every stored message that is, or shares, a tagged post; returns links added.

    Runs when a post is tagged, and at the end of every crawl as the safety net
    behind ``link_stored_message`` (which links each message as it is stored):
    it catches a post tagged in the web UI while the crawler was storing its
    shares, and messages stored by any other path. Never removes links: a
    message only leaves a tag when the tagging itself is deleted (or the
    message is).
    """
    taggings = list(MessageTagging.objects.all() if taggings is None else taggings)
    if not taggings:
        return 0
    members = resolve_origin_messages(t.origin for t in taggings)
    existing = set(
        TaggedMessage.objects.filter(tagging__in=taggings).values_list("tagging_id", "message_id").iterator()
    )
    links = [
        TaggedMessage(tagging=t, message_id=pk)
        for t in taggings
        for pk in members.get(t.origin, ())
        if (t.pk, pk) not in existing
    ]
    TaggedMessage.objects.bulk_create(links, batch_size=500, ignore_conflicts=True)
    return len(links)


def tag_post(message: Message, tag: MessageTag, *, note: str = "", tagged_by: Any = None) -> "MessageTagging":
    """Tag the post ``message`` is or shares — its original and every share — and link the stored ones.

    The tagged message itself is always linked, whatever the origin lookup finds:
    its chip, the ``?tag=`` lists and the purge exemption all read the links.
    Raises ``IntegrityError`` when the post already carries ``tag`` (check
    ``MessageTagging.objects.filter(tag=…, origin…)`` first).
    """
    channel_tid, post_tid = message_origin(message)
    tagging = MessageTagging.objects.create(
        tag=tag,
        origin_channel_tid=channel_tid,
        origin_post_tid=post_tid,
        message=message,
        note=note,
        tagged_by=tagged_by,
    )
    TaggedMessage.objects.create(tagging=tagging, message=message)
    sync_tag_members([tagging])
    return tagging


def with_message_counts(tags: models.QuerySet) -> models.QuerySet:
    """Annotate ``message_count``: stored messages carrying each tag, shares included."""
    return tags.annotate(message_count=models.Count("taggings__members__message", distinct=True))


class MessageTagging(BaseModel):
    """One tag on one post — the original and every share of it — with who applied it and a note.

    The post is identified by its Telegram origin (``message_origin``), so tagging
    any share of it is the same act as tagging the original. ``message`` is the
    message the analyst tagged from; :class:`TaggedMessage` lists every stored
    message carrying the tag (kept current by ``sync_tag_members``).
    """

    tag = models.ForeignKey(MessageTag, on_delete=models.CASCADE, related_name="taggings")
    # Telegram ids (not Channel pks), so a post from a private, unresolved channel
    # — known only by ``Message.forwarded_from_private`` — has an origin too.
    origin_channel_tid = models.BigIntegerField()
    origin_post_tid = models.BigIntegerField()
    message = models.ForeignKey(
        Message, on_delete=models.SET_NULL, null=True, blank=True, related_name="entered_taggings"
    )
    tagged_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="message_taggings",
    )
    note = models.TextField(blank=True, default="")

    class Meta:
        ordering = ["tag__key"]
        constraints = [
            models.UniqueConstraint(
                fields=["tag", "origin_channel_tid", "origin_post_tid"], name="webapp_messagetagging_post_unique"
            ),
        ]
        indexes = [
            models.Index(fields=["origin_channel_tid", "origin_post_tid"], name="webapp_tagging_origin_idx"),
        ]

    def __str__(self) -> str:
        return f"{self.tag} → post {self.origin_post_tid} of channel {self.origin_channel_tid}"

    @property
    def origin(self) -> tuple[int, int]:
        return self.origin_channel_tid, self.origin_post_tid

    @property
    def tagged_at(self):
        return self._created


class TaggedMessage(models.Model):
    """A stored message carrying a tagging: the tagged post itself or one of its shares."""

    tagging = models.ForeignKey(MessageTagging, on_delete=models.CASCADE, related_name="members")
    message = models.ForeignKey(Message, on_delete=models.CASCADE, related_name="tag_links")

    class Meta:
        ordering = ["tagging__tag__key"]
        constraints = [
            models.UniqueConstraint(fields=["tagging", "message"], name="webapp_taggedmessage_unique"),
        ]

    def __str__(self) -> str:
        return f"{self.tagging.tag} on message {self.message_id}"
