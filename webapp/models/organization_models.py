import datetime

from django.core.exceptions import ValidationError
from django.db import models
from django.utils.text import slugify

from webapp.models.base import BaseColorModel, BaseModel


class Organization(BaseColorModel):
    name = models.CharField(max_length=255)
    is_in_target = models.BooleanField(default=True)

    def __str__(self) -> str:
        return self.name

    @property
    def key(self) -> str:
        return slugify(self.name)


class ChannelAttribution(BaseModel):
    """A time-bounded attribution of a channel to an organization.

    A channel belongs to ``organization`` over the inclusive date interval
    ``[start, end]``. ``start=None`` extends back to the channel's creation;
    ``end=None`` extends up to the present. Periods for a single channel must
    not overlap (enforced in :meth:`clean`, the DRF serializer, and the admin
    inline formset — SQLite can't express a portable exclusion constraint).
    A period is *in-target* iff ``organization.is_in_target`` is true.
    """

    channel = models.ForeignKey("webapp.Channel", on_delete=models.CASCADE, related_name="attributions")
    organization = models.ForeignKey(Organization, on_delete=models.CASCADE, related_name="attributions")
    start = models.DateField(null=True, blank=True)
    end = models.DateField(null=True, blank=True)

    class Meta:
        ordering = ["channel_id", "start"]
        indexes = [
            models.Index(fields=["channel", "organization"], name="webapp_chattr_chan_org_idx"),
            models.Index(fields=["organization"], name="webapp_chattr_org_idx"),
            models.Index(fields=["channel", "start", "end"], name="webapp_chattr_chan_span_idx"),
        ]

    def __str__(self) -> str:
        lo = self.start.isoformat() if self.start else "…"
        hi = self.end.isoformat() if self.end else "…"
        return f"{self.channel_id} → {self.organization_id} [{lo}, {hi}]"

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
    def build_cache(cls, channel_ids) -> dict:
        """``{channel_id: [(org_id, start, end), …]}`` ordered by start, for org-at-date lookups."""
        cache: dict[int, list[tuple]] = {}
        if not channel_ids:
            return cache
        for cid, org_id, start, end in (
            cls.objects.filter(channel_id__in=channel_ids)
            .order_by("channel_id", "start")
            .values_list("channel_id", "organization_id", "start", "end")
        ):
            cache.setdefault(cid, []).append((org_id, start, end))
        return cache

    @staticmethod
    def org_at(cache: dict, channel_id: int, when: "datetime.date") -> int | None:
        """Organization id attributed to ``channel_id`` on ``when`` (null bounds = open). Periods don't overlap."""
        for org_id, start, end in cache.get(channel_id, ()):
            if (start is None or start <= when) and (end is None or end >= when):
                return org_id
        return None

    def clean(self) -> None:
        if self.start and self.end and self.start > self.end:
            raise ValidationError({"end": "End date must not be before start date."})
        if getattr(self, "_overlap_checked_by_formset", False):
            # The admin inline formset validates the channel's *submitted* timeline as
            # a whole (pairwise, in its clean()). Checking each row against the stale
            # DB siblings here would spuriously reject valid multi-row edits — e.g.
            # closing the open period and adding its successor in one save.
            return
        if self.channel_id is None:
            return
        siblings = ChannelAttribution.objects.filter(channel_id=self.channel_id)
        if self.pk:
            siblings = siblings.exclude(pk=self.pk)
        for other in siblings:
            if self._overlaps(self.start, self.end, other.start, other.end):
                raise ValidationError(
                    "Attribution periods for a channel must not overlap "
                    f"(conflicts with {other.organization} [{other.start or '…'}, {other.end or '…'}])."
                )
