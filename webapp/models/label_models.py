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
    default ``MODULEROLE`` basis — the roles the legacy ``Organization`` model
    used to play.
    """

    name = models.CharField(max_length=255)
    description = models.TextField(blank=True, default="")
    is_partition = models.BooleanField(default=False)
    is_primary = models.BooleanField(default=False)

    def __str__(self) -> str:
        return self.name

    @property
    def key(self) -> str:
        return slugify(self.name)

    @property
    def token(self) -> str:
        """The measure / community-strategy token selecting this group's partition."""
        return f"LABELGROUP{self.pk}"


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


class ChannelLabel(BaseModel):
    """A time-bounded membership of a channel in a label.

    The channel holds ``label`` over the inclusive date interval ``[start, end]``;
    ``start=None`` extends back to the channel's creation, ``end=None`` up to the
    present, and both ``None`` means "always" (the natural default for a static
    label such as a nation). Within a *partition* group the periods for one
    channel must not overlap — a channel holds at most one of that group's labels
    at a time; non-partition groups allow concurrent (and overlapping)
    memberships. Replaces the legacy ``ChannelAttribution``.
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
