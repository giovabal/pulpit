import datetime

from django.core.exceptions import ValidationError
from django.db import models
from django.utils.text import slugify

from webapp.models.base import BaseColorModel, BaseModel


class LabelGroup(BaseColorModel):
    """A named family of labels (e.g. "Organization", "Nation").

    When ``is_partition`` is true a channel may hold at most one of this group's
    labels at any given moment — its label periods *within the group* must not
    overlap (enforced in :meth:`ChannelLabel.clean`, the DRF serializer, and the
    admin inline formset). A partition group induces a node partition and is
    offered as a community-detection strategy / ``MODULEROLE`` basis under the
    token ``LABELGROUP<id>``.

    Exactly one group is ``is_primary``: it supplies a node's default colour, the
    "Organization" export column, the vacancy-analysis actor identity, and the
    default ``MODULEROLE`` basis.

    When ``is_container`` is true the group's labels are purely structural: they
    act as *parents* for labels of other groups (a "Continents" container whose
    "Europe" label parents the "Nation" labels France, Spain, …) via
    :class:`LabelParent`, and are never linked to channels directly (rejected in
    :meth:`ChannelLabel.clean` and the serializers). A container label can be
    selected on the home page to scope the dashboard stats to the channels
    holding any of its child labels.
    """

    name = models.CharField(max_length=255)
    description = models.TextField(blank=True, default="")
    is_partition = models.BooleanField(default=False)
    is_primary = models.BooleanField(default=False)
    is_container = models.BooleanField(default=False)

    def __str__(self) -> str:
        return self.name

    @property
    def key(self) -> str:
        return slugify(self.name)

    @property
    def token(self) -> str:
        """The measure / community-strategy token selecting this group's partition."""
        return f"LABELGROUP{self.pk}"

    def partition_conflicts(self) -> "list[tuple[ChannelLabel, ChannelLabel]]":
        """Pairs of this group's ``ChannelLabel`` periods that overlap for the same channel.

        Empty when the group already satisfies the partition constraint (at most one
        label per channel at any moment). A *non*-partition group may have accumulated
        overlapping memberships, so this is checked before switching ``is_partition`` on.
        """
        rows = list(
            ChannelLabel.objects.filter(label__group_id=self.pk)
            .select_related("channel", "label")
            .order_by("channel_id", "start")
        )
        by_channel: dict[int, list[ChannelLabel]] = {}
        for cl in rows:
            by_channel.setdefault(cl.channel_id, []).append(cl)
        conflicts: list[tuple[ChannelLabel, ChannelLabel]] = []
        for channel_rows in by_channel.values():
            for i in range(len(channel_rows)):
                for j in range(i + 1, len(channel_rows)):
                    a, b = channel_rows[i], channel_rows[j]
                    if ChannelLabel._overlaps(a.start, a.end, b.start, b.end):
                        conflicts.append((a, b))
        return conflicts

    @staticmethod
    def _fmt_period(cl: "ChannelLabel") -> str:
        lo = cl.start.isoformat() if cl.start else "…"
        hi = cl.end.isoformat() if cl.end else "…"
        return f"{lo} → {hi}"

    def partition_conflict_message(self, conflicts: "list[tuple[ChannelLabel, ChannelLabel]]", limit: int = 5) -> str:
        """A human-readable explanation of why the group cannot become a partition."""
        parts = [
            f"“{a.channel}” holds “{a.label.name}” ({self._fmt_period(a)}) and “{b.label.name}” ({self._fmt_period(b)})"
            for a, b in conflicts[:limit]
        ]
        msg = (
            f"Cannot make “{self.name}” a partition group: {len(conflicts)} overlapping label "
            "period(s) must be resolved first — " + "; ".join(parts)
        )
        if len(conflicts) > limit:
            msg += f"; and {len(conflicts) - limit} more"
        return msg + "."

    def clean(self) -> None:
        # A partition group requires non-overlapping periods per channel; refuse to become one
        # (or remain one) while conflicts exist, naming them so the operator can correct them.
        if self.is_partition and self.pk:
            conflicts = self.partition_conflicts()
            if conflicts:
                raise ValidationError({"is_partition": self.partition_conflict_message(conflicts)})
        # Unsetting container status would strand the child assignments hanging off this
        # group's labels — require the operator to clear them first, like the partition check.
        if self.pk and not self.is_container:
            child_count = LabelParent.objects.filter(parent_group_id=self.pk).count()
            if child_count:
                raise ValidationError(
                    {
                        "is_container": (
                            f"Cannot unset container: {child_count} label(s) are still assigned under "
                            f"“{self.name}” labels. Remove those assignments first."
                        )
                    }
                )
        # A container's labels only contain other labels — they are never linked to
        # channels directly. Refuse to become a container while such links exist.
        if self.pk and self.is_container:
            link_count = ChannelLabel.objects.filter(label__group_id=self.pk).count()
            if link_count:
                raise ValidationError(
                    {
                        "is_container": (
                            f"Cannot make “{self.name}” a container: {link_count} channel-label period(s) "
                            "still point at its labels. Remove those channel assignments first."
                        )
                    }
                )


class Label(BaseColorModel):
    """A single label within a :class:`LabelGroup`.

    A channel is *in target* iff it holds at least one label whose
    ``is_in_target`` is true over an interval covering the date in question
    (see :func:`network.utils.channel_cutoff_q`).
    """

    group = models.ForeignKey(LabelGroup, on_delete=models.CASCADE, related_name="labels")
    name = models.CharField(max_length=255)
    is_in_target = models.BooleanField(default=False)

    class Meta:
        ordering = ["group_id", "name"]

    def __str__(self) -> str:
        return f"{self.group.name}: {self.name}"

    @property
    def key(self) -> str:
        return slugify(self.name)

    @classmethod
    def from_filter_param(cls, raw) -> "Label | None":
        """Resolve a home-page ``?filter=`` query-string value to a container-group label.

        Non-integer, unknown, or non-container values select nothing (the
        unfiltered dashboard) rather than erroring — the param travels in
        user-editable URLs.
        """
        raw = str(raw or "").strip()
        if not raw.isdigit():
            return None
        return cls.objects.select_related("group").filter(pk=int(raw), group__is_container=True).first()

    @classmethod
    def parse_filter_labels(cls, raw) -> list[int]:
        """Parse a ``--filter-labels`` CSV into validated container-label ids.

        Shared by ``structural_analysis`` and ``crawl_channels``. Raises
        ``ValueError`` on non-integer tokens or ids that are not labels of a
        container group, so a scope filter fails loudly instead of silently
        matching nothing.
        """
        if not raw:
            return []
        try:
            ids = [int(s.strip()) for s in str(raw).split(",") if s.strip()]
        except ValueError as e:
            raise ValueError("--filter-labels must be a comma-separated list of label ids.") from e
        known = set(cls.objects.filter(pk__in=ids, group__is_container=True).values_list("pk", flat=True))
        unknown = [str(pk) for pk in ids if pk not in known]
        if unknown:
            raise ValueError(
                f"--filter-labels: not container-group label id(s): {', '.join(unknown)}. "
                "Only labels of a container group (Manage → Labels) can filter the selection."
            )
        return ids


class LabelParent(BaseModel):
    """A child label's membership under a *container* label.

    ``parent`` is a label of a container group (e.g. "Continents: Europe");
    ``label`` is the child, a label of a *different* group (e.g. "Nation:
    France"). Within one container group a label has at most one parent — a
    nation belongs to a single continent — enforced by the unique
    ``(label, parent_group)`` constraint. ``parent_group`` is denormalised from
    ``parent.group`` (kept in sync by :meth:`save`) precisely so that constraint
    can live in the database.
    """

    label = models.ForeignKey(Label, on_delete=models.CASCADE, related_name="parent_links")
    parent = models.ForeignKey(Label, on_delete=models.CASCADE, related_name="child_links")
    parent_group = models.ForeignKey(LabelGroup, on_delete=models.CASCADE, related_name="+", editable=False)

    class Meta:
        ordering = ["parent_id", "id"]
        constraints = [
            models.UniqueConstraint(fields=["label", "parent_group"], name="webapp_lblparent_lbl_grp_uniq"),
        ]
        indexes = [
            models.Index(fields=["parent"], name="webapp_lblparent_parent_idx"),
        ]

    def __str__(self) -> str:
        return f"{self.label} → {self.parent}"

    def clean(self) -> None:
        if self.label_id is None or self.parent_id is None:
            return
        if not self.parent.group.is_container:
            raise ValidationError({"parent": "The parent label must belong to a container group."})
        if self.parent.group_id == self.label.group_id:
            raise ValidationError({"label": "A container label cannot parent a label of its own group."})

    def save(self, *args, **kwargs) -> None:
        # Keep the denormalised FK true to the parent's group no matter what the
        # caller set, so the (label, parent_group) uniqueness can never be sidestepped.
        self.parent_group_id = self.parent.group_id
        super().save(*args, **kwargs)


class ChannelLabel(BaseModel):
    """A time-bounded membership of a channel in a label.

    The channel holds ``label`` over the inclusive date interval ``[start, end]``;
    ``start=None`` extends back to the channel's creation, ``end=None`` up to the
    present, and both ``None`` means "always" (the natural default for a static
    label such as a nation). Within a *partition* group the periods for one
    channel must not overlap — a channel holds at most one of that group's labels
    at a time; non-partition groups allow concurrent (and overlapping)
    memberships.
    """

    channel = models.ForeignKey("webapp.Channel", on_delete=models.CASCADE, related_name="channel_labels")
    label = models.ForeignKey(Label, on_delete=models.CASCADE, related_name="channel_labels")
    start = models.DateField(null=True, blank=True)
    end = models.DateField(null=True, blank=True)

    class Meta:
        ordering = ["channel_id", "start"]
        indexes = [
            models.Index(fields=["channel", "label"], name="webapp_chlabel_chan_lbl_idx"),
            models.Index(fields=["label"], name="webapp_chlabel_lbl_idx"),
            models.Index(fields=["channel", "start", "end"], name="webapp_chlabel_span_idx"),
        ]

    def __str__(self) -> str:
        lo = self.start.isoformat() if self.start else "…"
        hi = self.end.isoformat() if self.end else "…"
        return f"{self.channel_id} → {self.label_id} [{lo}, {hi}]"

    @staticmethod
    def _overlaps(
        s1: "datetime.date | None",
        e1: "datetime.date | None",
        s2: "datetime.date | None",
        e2: "datetime.date | None",
    ) -> bool:
        """Whether two inclusive date intervals overlap (``None`` = unbounded).

        Inclusive on both ends, so ``end=X`` and a sibling ``start=X`` *do*
        overlap; an adjacent period must start at ``X + 1 day``.
        """
        lo1, hi1 = s1 or datetime.date.min, e1 or datetime.date.max
        lo2, hi2 = s2 or datetime.date.min, e2 or datetime.date.max
        return lo1 <= hi2 and lo2 <= hi1

    @classmethod
    def build_cache(cls, channel_ids, group_id: int | None = None) -> dict:
        """``{channel_id: [(label_id, start, end), …]}`` ordered by start, for label-at-date lookups.

        Filtered to ``group_id`` when given (the usual case: resolving one
        partition group's active label at a date). Within a partition group the
        periods don't overlap, so :meth:`label_at` can return the first match.
        """
        cache: dict[int, list[tuple]] = {}
        if not channel_ids:
            return cache
        qs = cls.objects.filter(channel_id__in=channel_ids)
        if group_id is not None:
            qs = qs.filter(label__group_id=group_id)
        for cid, label_id, start, end in qs.order_by("channel_id", "start").values_list(
            "channel_id", "label_id", "start", "end"
        ):
            cache.setdefault(cid, []).append((label_id, start, end))
        return cache

    @staticmethod
    def label_at(cache: dict, channel_id: int, when: "datetime.date") -> int | None:
        """Label id held by ``channel_id`` on ``when`` (null bounds = open).

        Returns the first period covering ``when``; for a cache scoped to a
        single partition group that is the unique active label.
        """
        for label_id, start, end in cache.get(channel_id, ()):
            if (start is None or start <= when) and (end is None or end >= when):
                return label_id
        return None

    def clean(self) -> None:
        if self.start and self.end and self.start > self.end:
            raise ValidationError({"end": "End date must not be before start date."})
        # Container-group labels only contain other labels (LabelParent); channels are
        # never attributed to them directly. Checked before the formset early-return —
        # the admin formset only re-validates overlap, not this.
        if self.label_id is not None and self.label.group.is_container:
            raise ValidationError(
                {
                    "label": "Labels of a container group cannot be assigned to channels — they only contain other labels."
                }
            )
        if getattr(self, "_overlap_checked_by_formset", False):
            # The admin inline formset validates the channel's *submitted* timeline as
            # a whole (pairwise, in its clean()). Checking each row against the stale
            # DB siblings here would spuriously reject valid multi-row edits.
            return
        if self.channel_id is None or self.label_id is None:
            return
        # Overlap is constrained only inside a partition group: there a channel holds
        # at most one label at a time. Non-partition groups allow concurrent memberships.
        if not self.label.group.is_partition:
            return
        siblings = ChannelLabel.objects.filter(
            channel_id=self.channel_id, label__group_id=self.label.group_id
        ).select_related("label", "label__group")
        if self.pk:
            siblings = siblings.exclude(pk=self.pk)
        for other in siblings:
            if self._overlaps(self.start, self.end, other.start, other.end):
                raise ValidationError(
                    "Label periods within a partition group must not overlap "
                    f"(conflicts with {other.label} [{other.start or '…'}, {other.end or '…'}])."
                )
