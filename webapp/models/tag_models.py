import re
import unicodedata
from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass, field
from functools import reduce
from itertools import batched
from operator import or_
from typing import Any

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models, transaction
from django.db.models import Q
from django.utils import timezone

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


# A tag's full name joins its ancestors' names and its own: "Hand gestures › Nazi
# salute". Typed paths may use "/" too; neither character may appear in a name.
TAG_PATH_SEPARATOR = " › "
_PATH_SPLIT_RE = re.compile(r"[/›]")


def split_tag_path(raw: str) -> list[str]:
    """``"Hand gestures / Nazi salute"`` → ``["Hand gestures", "Nazi salute"]`` (empty segments dropped)."""
    return [name for name in (normalize_tag_name(part) for part in _PATH_SPLIT_RE.split(raw or "")) if name]


def tag_name_error(name: str) -> str:
    """Why ``name`` (already normalised) can't name a tag, or ``""`` when it can."""
    if not name:
        return "A tag needs a name."
    if _PATH_SPLIT_RE.search(name):
        return "A tag name can't contain “/” or “›”: they separate a tag from its sub-tags."
    if len(name) > 64:
        return "A tag name has at most 64 characters."
    return ""


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

    Tags nest: a tag may sit under a ``parent`` (``Hand gestures › Nazi salute``),
    to any depth; a tag with no parent and no children is a plain, single-level
    tag. A sub-tag implies its ancestors without storing them — filtering by a tag
    takes its whole branch (:meth:`TagTree.branch`) — and a post never carries a
    tag together with one of its ancestors: tagging it with the more specific one
    *refines* the broader tagging (:func:`tag_post`), and a move or merge that would
    pair them folds the broader one away (:func:`fold_implied_taggings`). Names are
    unique among siblings (and among top-level tags), not across the tree.
    """

    name = models.CharField(max_length=64)
    key = models.CharField(max_length=64, editable=False)
    description = models.TextField(blank=True, default="")
    color = ColorField(default=next_tag_color)
    # PROTECT: a tag with sub-tags is deleted only once they are moved or deleted.
    parent = models.ForeignKey(
        "self",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="children",
        help_text="The broader tag this one specifies; empty for a top-level tag.",
    )

    class Meta:
        ordering = ["key"]
        constraints = [
            models.UniqueConstraint(fields=["parent", "key"], name="webapp_messagetag_sibling_unique"),
            # NULL parents never collide in a composite unique index (SQLite and
            # PostgreSQL alike), so top-level names need their own constraint.
            models.UniqueConstraint(
                fields=["key"], condition=Q(parent__isnull=True), name="webapp_messagetag_root_unique"
            ),
        ]

    def __str__(self) -> str:
        return self.name

    @property
    def path(self) -> str:
        """``"Hand gestures › Nazi salute"``: one query per ancestor — use :class:`TagTree` for many tags."""
        names = [self.name]
        parent = self.parent
        while parent is not None:
            names.append(parent.name)
            parent = parent.parent
        return TAG_PATH_SEPARATOR.join(reversed(names))

    def clean(self) -> None:
        super().clean()
        self.name = normalize_tag_name(self.name)
        error = tag_name_error(self.name)
        if error:
            raise ValidationError({"name": error})
        if self.pk is not None and self.parent_id is not None:
            if self.parent_id in TagTree.load().branch([self.pk]):
                raise ValidationError({"parent": "A tag can't go under itself or one of its sub-tags."})
        # The (parent, key) constraints name ``key``, which forms leave out (not
        # editable), so Django's constraint validation would skip them.
        clash = sibling_clash(self.name, self.parent, exclude_pk=self.pk)
        if clash:
            raise ValidationError({"name": clash})

    def save(self, *args, **kwargs) -> None:
        self.name = normalize_tag_name(self.name)
        self.key = tag_key(self.name)
        update_fields = kwargs.get("update_fields")
        moved = False
        if self.pk is not None and (update_fields is None or "parent" in update_fields):
            old_parent = list(MessageTag.objects.filter(pk=self.pk).values_list("parent_id", flat=True))
            moved = bool(old_parent) and old_parent[0] != self.parent_id
            if moved and self.parent_id is not None and self.parent_id in TagTree.load().branch([self.pk]):
                raise ValueError("A tag can't go under itself or one of its sub-tags.")
        with transaction.atomic():
            super().save(*args, **kwargs)
            if moved:
                fold_implied_taggings()

    def merge_into(self, target: "MessageTag") -> int:
        """Move this tag's posts and sub-tags onto ``target``, then delete this tag.

        A post already carrying ``target`` keeps that tagging; its note is filled
        from this tag's tagging only when it was empty. Each sub-tag moves under
        ``target``, or — when ``target`` already has a sub-tag of the same name —
        merges into it, recursively. A post left carrying a tag and one of its
        ancestors keeps only the more specific one. Merging into one of this tag's
        own sub-tags is refused. Returns the number of messages that joined
        ``target``'s branch.
        """
        if target.pk == self.pk:
            raise ValueError("Cannot merge a tag into itself.")
        tree = TagTree.load()
        if target.pk in tree.branch([self.pk]):
            raise ValueError("Cannot merge a tag into one of its own sub-tags.")
        with transaction.atomic():
            before = _branch_message_count(target)
            self._merge_into(target)
            fold_implied_taggings()
            after = _branch_message_count(target)
        return after - before

    def _merge_into(self, target: "MessageTag") -> None:
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
        target_children = {child.key: child for child in target.children.all()}
        for child in list(self.children.all()):
            twin = target_children.get(child.key)
            if twin is None:
                # A queryset update, not save(): merge_into folds implied taggings once, at the end.
                MessageTag.objects.filter(pk=child.pk).update(parent=target, _updated=timezone.now())
            else:
                child._merge_into(twin)
        self.delete()
        sync_tag_members(moved)


def sibling_clash(name: str, parent: "MessageTag | None", *, exclude_pk: int | None = None) -> str:
    """Why ``name`` can't go under ``parent`` (a sibling already has it), or ``""``."""
    clash = MessageTag.objects.filter(key=tag_key(name), parent=parent)
    if exclude_pk is not None:
        clash = clash.exclude(pk=exclude_pk)
    other = clash.first()
    if other is None:
        return ""
    if parent is None:
        return f"A top-level tag named “{other.name}” already exists."
    return f"“{parent.name}” already has a sub-tag named “{other.name}”."


class TagTree:
    """Every tag at once, with the parent/child links walked in memory.

    The tag table holds a few dozen rows, so one query and a dictionary beat
    recursive SQL: subtrees for filters (:meth:`branch`), paths for display,
    depth-first order for lists, path resolution for ``tag:`` tokens and for
    tags created by typing a path (:meth:`match`, :func:`plan_tag_path`).
    """

    def __init__(self, tags: Iterable[MessageTag]) -> None:
        self.by_id: dict[int, MessageTag] = {tag.pk: tag for tag in tags}
        self.children: dict[int | None, list[MessageTag]] = defaultdict(list)
        for tag in self.by_id.values():
            parent = tag.parent_id if tag.parent_id in self.by_id else None
            self.children[parent].append(tag)
        for siblings in self.children.values():
            siblings.sort(key=lambda t: (t.key, t.pk))

    @classmethod
    def load(cls) -> "TagTree":
        return cls(MessageTag.objects.all())

    def lineage(self, tag_id: int) -> list[MessageTag]:
        """The tag and its ancestors, top-level tag first (empty for an unknown id)."""
        out: list[MessageTag] = []
        seen: set[int] = set()
        current: int | None = tag_id
        while current is not None and current not in seen and current in self.by_id:
            seen.add(current)
            tag = self.by_id[current]
            out.append(tag)
            current = tag.parent_id
        return out[::-1]

    def ancestor_ids(self, tag_id: int) -> list[int]:
        """The tag's ancestors, top-level tag first (the tag itself left out)."""
        return [tag.pk for tag in self.lineage(tag_id)[:-1]]

    def path(self, tag_id: int) -> str:
        return TAG_PATH_SEPARATOR.join(tag.name for tag in self.lineage(tag_id))

    def ancestry(self, tag_id: int) -> str:
        """The ancestors' part of the path, separator included (``"Hand gestures › "``), or ``""``."""
        names = [tag.name for tag in self.lineage(tag_id)[:-1]]
        return TAG_PATH_SEPARATOR.join(names) + TAG_PATH_SEPARATOR if names else ""

    def branch(self, tag_ids: Iterable[int]) -> set[int]:
        """The given tags and all their sub-tags, to any depth (unknown ids dropped)."""
        out: set[int] = set()
        stack = [tag_id for tag_id in tag_ids if tag_id in self.by_id]
        while stack:
            tag_id = stack.pop()
            if tag_id in out:
                continue
            out.add(tag_id)
            stack.extend(child.pk for child in self.children.get(tag_id, ()))
        return out

    def is_ancestor(self, ancestor_id: int, tag_id: int) -> bool:
        return ancestor_id in self.ancestor_ids(tag_id)

    def depth_first(self) -> list[MessageTag]:
        """Every tag, each followed by its sub-tags, siblings by name; sets ``depth`` (0 = top level)."""
        out: list[MessageTag] = []

        def walk(parent: int | None, depth: int) -> None:
            for tag in self.children.get(parent, ()):
                tag.depth = depth
                out.append(tag)
                walk(tag.pk, depth + 1)

        walk(None, 0)
        return out

    def from_root(self, keys: list[str]) -> MessageTag | None:
        """The tag reached from a top-level tag by these keys, if any."""
        tag: MessageTag | None = None
        parent: int | None = None
        for key in keys:
            tag = next((t for t in self.children.get(parent, ()) if t.key == key), None)
            if tag is None:
                return None
            parent = tag.pk
        return tag

    def match(self, raw: str | list[str]) -> list[MessageTag]:
        """The tags a typed path names: the one reached from the top level, else every tag whose path ends with it.

        ``"Nazi salute"`` finds that tag wherever it sits; ``"Hand gestures/Nazi
        salute"`` the sub-tag of that name; a path that starts at a top-level tag
        is exact, so a top-level ``Other`` wins over ``Flags › Other``.
        """
        names = split_tag_path(raw) if isinstance(raw, str) else raw
        keys = [tag_key(name) for name in names]
        if not keys:
            return []
        exact = self.from_root(keys)
        if exact is not None:
            return [exact]
        n = len(keys)
        found = [tag for tag in self.by_id.values() if [t.key for t in self.lineage(tag.pk)][-n:] == keys]
        return sorted(found, key=lambda t: tag_key(self.path(t.pk)))


@dataclass
class TagPathPlan:
    """How a typed path resolves: an existing ``tag``, or the names to create under ``anchor``."""

    tag: MessageTag | None = None
    anchor: MessageTag | None = None
    create: list[str] = field(default_factory=list)

    def realise(self) -> MessageTag:
        """The tag, creating the missing ones; a sub-tag takes its parent's colour."""
        if self.tag is not None:
            return self.tag
        parent = self.anchor
        for name in self.create:
            extra = {"color": parent.color} if parent is not None else {}
            parent = MessageTag.objects.create(name=name, parent=parent, **extra)
        assert parent is not None
        return parent


def plan_tag_path(raw: str, tree: TagTree) -> TagPathPlan:
    """Resolve a typed tag name or path (``"Hand gestures/Kühnen salute"``) without writing anything.

    A path naming one tag (:meth:`TagTree.match`) is that tag. Otherwise its
    longest leading part that names one tag is the anchor and the rest is created
    under it; with no such part the whole path is created from the top level.
    Raises ``ValueError`` when a part names several tags, or a name is invalid.
    """
    names = split_tag_path(raw)
    if not names:
        raise ValueError("Give a tag name.")
    for name in names:
        error = tag_name_error(name)
        if error:
            raise ValueError(error)
    for end in range(len(names), 0, -1):
        found = tree.match(names[:end])
        if len(found) > 1:
            paths = ", ".join(f"“{tree.path(t.pk)}”" for t in found)
            raise ValueError(f"“{TAG_PATH_SEPARATOR.join(names[:end])}” could be {paths}: type the full path.")
        if found:
            if end == len(names):
                return TagPathPlan(tag=found[0])
            return TagPathPlan(anchor=found[0], create=names[end:])
    return TagPathPlan(create=names)


def _join_notes(kept: str, added: str) -> str:
    if not added or added == kept:
        return kept
    if not kept:
        return added
    return f"{kept}; {added}"


def _branch_message_count(tag: MessageTag) -> int:
    branch = TagTree.load().branch([tag.pk])
    return TaggedMessage.objects.filter(tagging__tag_id__in=branch).values("message_id").distinct().count()


def tag_message_counts(tree: TagTree) -> dict[int, tuple[int, int]]:
    """``{tag id: (messages carrying the tag itself, messages carrying it or a sub-tag)}``, shares included."""
    by_tag: dict[int, set[int]] = defaultdict(set)
    for tag_id, message_id in TaggedMessage.objects.values_list("tagging__tag_id", "message_id").iterator():
        by_tag[tag_id].add(message_id)
    counts: dict[int, tuple[int, int]] = {}
    for tag_id in tree.by_id:
        branch = tree.branch([tag_id])
        total = set().union(*(by_tag.get(t, set()) for t in branch)) if len(branch) > 1 else by_tag.get(tag_id, set())
        counts[tag_id] = (len(by_tag.get(tag_id, ())), len(total))
    return counts


def tags_in_tree_order(*, counts: bool = True, tree: TagTree | None = None) -> list[MessageTag]:
    """Every tag depth-first, each with ``depth``, ``path``, ``ancestry``, ``has_children`` and — with
    ``counts`` — ``own_count`` (messages carrying the tag itself) and ``message_count`` (its branch)."""
    tree = tree or TagTree.load()
    message_counts = tag_message_counts(tree) if counts else {}
    tags = tree.depth_first()
    for tag in tags:
        tag.tree_path = tree.path(tag.pk)
        tag.ancestry = tree.ancestry(tag.pk)
        tag.has_children = bool(tree.children.get(tag.pk))
        if counts:
            tag.own_count, tag.message_count = message_counts[tag.pk]
    return tags


def fold_implied_taggings() -> int:
    """Keep a post from carrying a tag and one of its ancestors: drop the broader tagging.

    Run after a tag moves or merges. The broader tagging's note is added to the
    narrower one's, and its stored messages are linked to the narrower tagging
    (they share the post, but the tagged message is linked whatever the origin
    lookup finds). Returns the taggings removed.
    """
    tree = TagTree.load()
    by_post: dict[tuple[int, int], list[MessageTagging]] = defaultdict(list)
    for tagging in MessageTagging.objects.all():
        by_post[tagging.origin].append(tagging)
    removed = 0
    for taggings in by_post.values():
        if len(taggings) < 2:
            continue
        for broad in taggings:
            narrower = sorted(
                (
                    t
                    for t in taggings
                    if t.pk is not None and t is not broad and tree.is_ancestor(broad.tag_id, t.tag_id)
                ),
                key=lambda t: tag_key(tree.path(t.tag_id)),
            )
            if not narrower or broad.pk is None:
                continue
            kept = narrower[0]
            note = _join_notes(kept.note, broad.note)
            if note != kept.note:
                kept.note = note
                kept.save(update_fields=["note", "_updated"])
            TaggedMessage.objects.bulk_create(
                [
                    TaggedMessage(tagging=kept, message_id=pk)
                    for pk in broad.members.values_list("message_id", flat=True)
                ],
                ignore_conflicts=True,
            )
            broad.delete()  # also clears broad.pk, so later passes skip it
            removed += 1
    return removed


class ImpliedTagError(ValueError):
    """The post already carries a sub-tag of the tag being added, which implies it."""


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

    When the post carries an ancestor of ``tag`` (``Hand gestures``, now tagged
    ``Hand gestures › Nazi salute``), that tagging is *refined*: it takes ``tag``,
    the new note joins its note, and it records the new tagger and time, keeping
    its links. The returned tagging's ``replaced`` lists the tags it replaced (empty
    for a new tagging). Raises :class:`ImpliedTagError` when the post carries a
    sub-tag of ``tag``, and ``IntegrityError`` when it already carries ``tag``
    (check ``MessageTagging.objects.filter(tag=…, origin…)`` first).
    """
    channel_tid, post_tid = message_origin(message)
    with transaction.atomic():
        on_post = list(MessageTagging.objects.filter(origin_channel_tid=channel_tid, origin_post_tid=post_tid))
        broader: list[MessageTagging] = []
        if on_post:
            tree = TagTree.load()
            narrower = [t for t in on_post if tree.is_ancestor(tag.pk, t.tag_id)]
            if narrower:
                raise ImpliedTagError(
                    f"This post already carries “{tree.path(narrower[0].tag_id)}”, which implies “{tree.path(tag.pk)}”."
                )
            ancestors = set(tree.ancestor_ids(tag.pk))
            broader = [t for t in on_post if t.tag_id in ancestors]
        if broader:
            tagging, *others = broader
            replaced = [MessageTag.objects.get(pk=t.tag_id) for t in broader]
            for other in others:
                tagging.note = _join_notes(tagging.note, other.note)
                TaggedMessage.objects.bulk_create(
                    [
                        TaggedMessage(tagging=tagging, message_id=pk)
                        for pk in other.members.values_list("message_id", flat=True)
                    ],
                    ignore_conflicts=True,
                )
                other.delete()
            tagging.tag = tag
            tagging.note = _join_notes(tagging.note, note)
            tagging._created = timezone.now()
            fields = ["tag", "note", "_created", "_updated"]
            if tagged_by is not None:
                tagging.tagged_by = tagged_by
                fields.append("tagged_by")
            tagging.save(update_fields=fields)
        else:
            replaced = []
            tagging = MessageTagging.objects.create(
                tag=tag,
                origin_channel_tid=channel_tid,
                origin_post_tid=post_tid,
                message=message,
                note=note,
                tagged_by=tagged_by,
            )
        TaggedMessage.objects.bulk_create([TaggedMessage(tagging=tagging, message=message)], ignore_conflicts=True)
        sync_tag_members([tagging])
    tagging.replaced = replaced
    return tagging


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
