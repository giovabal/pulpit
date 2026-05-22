import re
from collections import Counter
from typing import Any, ClassVar

from django.db import models
from django.db.models import Avg, Count, Sum
from django.db.models.functions import TruncMonth
from django.http import HttpRequest, JsonResponse
from django.shortcuts import get_object_or_404
from django.views import View

from stats.queries import channel_month_spine, global_month_spine, reindex_to_spine
from webapp.models import Channel, Message, MessageReaction
from webapp.utils.emoji import emoji_present

import pandas as pd

_URL_RE = re.compile(r"https?://(?:www\.)?([^/\s?#\[<>\"\']+)", re.IGNORECASE)
_EMAIL_RE = re.compile(r"\b[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}\b")
_TELEGRAM_HOSTS = frozenset({"t.me", "telegram.me", "telegram.org", "telegra.ph", "telesco.pe"})


class _GlobalTimeSeriesBase(View):
    annotate_field: ClassVar[str]
    y_label: ClassVar[str]

    def get_annotation(self) -> Count | Sum | Avg:
        raise NotImplementedError

    def get(self, request: HttpRequest, *args: Any, **kwargs: Any) -> JsonResponse:
        spine = global_month_spine()
        if not spine:
            return JsonResponse({"labels": [], "values": [], "y_label": self.y_label})

        from network.utils import channel_cutoff_q

        in_target_pks = Channel.objects.in_target().values("pk")
        monthly_data = (
            Message.objects.alive()
            .filter(channel__in=in_target_pks, date__isnull=False)
            .filter(channel_cutoff_q())
            .annotate(month=TruncMonth("date"))
            .values("month")
            .annotate(**{self.annotate_field: self.get_annotation()})
            .order_by("month")
        )
        df = pd.DataFrame(
            [{"month": e["month"].strftime("%Y-%m"), self.annotate_field: e[self.annotate_field]} for e in monthly_data]
        )
        df = (
            reindex_to_spine(df, self.annotate_field, spine)
            if not df.empty
            else pd.DataFrame({"month": spine, self.annotate_field: [0] * len(spine)})
        )
        return JsonResponse(
            {"labels": list(df["month"]), "values": list(df[self.annotate_field]), "y_label": self.y_label}
        )


class MessagesHistoryDataView(_GlobalTimeSeriesBase):
    annotate_field = "total_messages"
    y_label = "messages"

    def get_annotation(self) -> Count:
        return Count("id")


class ActiveChannelsHistoryDataView(_GlobalTimeSeriesBase):
    annotate_field = "total_active_channels"
    y_label = "active channels"

    def get_annotation(self) -> Count:
        return Count("channel", distinct=True)


class ForwardsHistoryDataView(_GlobalTimeSeriesBase):
    annotate_field = "total_forwards"
    y_label = "forwards"

    def get_annotation(self) -> Count:
        return Count("id", filter=models.Q(forwarded_from__isnull=False))


class ViewsHistoryDataView(_GlobalTimeSeriesBase):
    annotate_field = "total_views"
    y_label = "views"

    def get_annotation(self) -> Sum:
        return Sum("views", default=0)


class AvgInvolvementHistoryDataView(_GlobalTimeSeriesBase):
    annotate_field = "avg_involvement"
    y_label = "avg views"

    def get_annotation(self) -> Avg:
        return Avg("views", default=0)


class _ChannelTimeSeriesBase(View):
    """Per-channel monthly aggregation pipeline.

    Mirrors ``_GlobalTimeSeriesBase``: subclasses only declare ``annotate_field``,
    ``y_label``, and ``get_annotation()`` (plus optional ``extra_filters`` and
    ``post_process_value`` / ``get_queryset`` hooks for the two outliers).
    """

    annotate_field: ClassVar[str]
    y_label: ClassVar[str]
    extra_filters: ClassVar[dict[str, Any]] = {}

    def _msg_qs(self, channel: Channel, **filters):
        """Base Message queryset for a channel, respecting out_of_target_after and excluding lost."""
        qs = Message.objects.alive().filter(channel=channel, **filters)
        if channel.out_of_target_after:
            qs = qs.filter(date__date__lte=channel.out_of_target_after)
        return qs

    def get_annotation(self) -> Count | Sum | Avg:
        raise NotImplementedError

    def get_queryset(self, channel: Channel):
        """Queryset that feeds the monthly aggregation. Override for views that
        scope to in-target channels rather than the subject channel itself
        (e.g. ``ChannelForwardsReceivedHistoryView``)."""
        return self._msg_qs(channel, date__isnull=False, **self.extra_filters)

    def post_process_value(self, value: Any) -> Any:
        """Post-process each monthly value before serialising. Default: identity."""
        return value

    def _get_monthly_data(self, channel: Channel) -> list[dict]:
        qs = (
            self.get_queryset(channel)
            .annotate(month=TruncMonth("date"))
            .values("month")
            .annotate(**{self.annotate_field: self.get_annotation()})
            .order_by("month")
        )
        return [
            {
                "month": e["month"].strftime("%Y-%m"),
                self.annotate_field: self.post_process_value(e[self.annotate_field]),
            }
            for e in qs
        ]

    def get(self, request: HttpRequest, pk: int, *args: Any, **kwargs: Any) -> JsonResponse:
        channel = get_object_or_404(Channel, pk=pk)
        spine = channel_month_spine(channel)
        if not spine:
            return JsonResponse({"labels": [], "values": [], "y_label": self.y_label})
        rows = self._get_monthly_data(channel)
        df = pd.DataFrame(rows)
        df = (
            reindex_to_spine(df, self.annotate_field, spine)
            if not df.empty
            else pd.DataFrame({"month": spine, self.annotate_field: [0] * len(spine)})
        )
        return JsonResponse(
            {"labels": list(df["month"]), "values": list(df[self.annotate_field]), "y_label": self.y_label}
        )


class ChannelMessagesHistoryView(_ChannelTimeSeriesBase):
    annotate_field = "total_messages"
    y_label = "messages"

    def get_annotation(self) -> Count:
        return Count("id")


class ChannelViewsHistoryView(_ChannelTimeSeriesBase):
    annotate_field = "total_views"
    y_label = "views"
    extra_filters = {"views__isnull": False}

    def get_annotation(self) -> Sum:
        return Sum("views")


class ChannelForwardsHistoryView(_ChannelTimeSeriesBase):
    annotate_field = "total_forwards"
    y_label = "forwards sent"
    extra_filters = {"forwarded_from__isnull": False}

    def get_annotation(self) -> Count:
        return Count("id")


class ChannelForwardsReceivedHistoryView(_ChannelTimeSeriesBase):
    """Forwards received by this channel from in-target channels — needs a different
    base queryset (other channels' messages forwarding from us), so it overrides
    ``get_queryset`` instead of declaring ``extra_filters``."""

    annotate_field = "total_forwards_received"
    y_label = "forwards received"

    def get_queryset(self, channel: Channel):
        from network.utils import channel_cutoff_q

        in_target_pks = Channel.objects.in_target().values("pk")
        return (
            Message.objects.alive()
            .filter(channel__in=in_target_pks, forwarded_from=channel, date__isnull=False)
            .filter(channel_cutoff_q())
        )

    def get_annotation(self) -> Count:
        return Count("id")


class ChannelAvgInvolvementHistoryView(_ChannelTimeSeriesBase):
    annotate_field = "avg_involvement"
    y_label = "avg views"

    def get_annotation(self) -> Avg:
        return Avg("views", default=0)

    def post_process_value(self, value: Any) -> int:
        return round(value)


class ChannelCrossRefsView(_ChannelTimeSeriesBase):
    def get(self, request: HttpRequest, pk: int, *args: Any, **kwargs: Any) -> JsonResponse:
        channel = get_object_or_404(Channel, pk=pk)
        in_target_pks = Channel.objects.in_target().values("pk")

        from network.utils import channel_cutoff_q

        fwd_out = Counter(
            self._msg_qs(channel, forwarded_from__isnull=False)
            .exclude(forwarded_from=channel)
            .values_list("forwarded_from", flat=True)
        )
        ref_out = Counter(
            cpk
            for cpk in self._msg_qs(channel).values_list("references", flat=True)
            if cpk is not None and cpk != channel.pk
        )
        mentioned = fwd_out + ref_out

        fwd_in = Counter(
            Message.objects.alive()
            .filter(channel__in=in_target_pks, forwarded_from=channel)
            .filter(channel_cutoff_q())
            .values_list("channel", flat=True)
        )
        ref_in = Counter(
            Message.objects.alive()
            .filter(channel__in=in_target_pks, references=channel)
            .filter(channel_cutoff_q())
            .exclude(channel=channel)
            .values_list("channel", flat=True)
        )
        mentioning = fwd_in + ref_in

        all_pks = [cpk for cpk in set(mentioned) | set(mentioning) if cpk is not None]
        channel_map = {
            c.pk: {"title": c.title or str(c.telegram_id), "url": c.get_absolute_url(), "telegram_url": c.telegram_url}
            for c in Channel.objects.filter(pk__in=all_pks)
        }

        def serialize(counter: Counter) -> list[dict]:
            return [
                {
                    "title": channel_map.get(cpk, {}).get("title", str(cpk)),
                    "url": channel_map.get(cpk, {}).get("url", ""),
                    "telegram_url": channel_map.get(cpk, {}).get("telegram_url", ""),
                    "count": count,
                }
                for cpk, count in counter.most_common()
                if cpk is not None
            ]

        return JsonResponse({"mentioned": serialize(mentioned), "mentioning": serialize(mentioning)})


class ReactionsHistoryDataView(View):
    def get(self, request: HttpRequest, *args: Any, **kwargs: Any) -> JsonResponse:
        spine = global_month_spine()
        if not spine:
            return JsonResponse({"labels": [], "series": [], "y_label": "reactions"})

        from network.utils import channel_cutoff_q

        in_target_pks = Channel.objects.in_target().values("pk")
        cutoff_q = channel_cutoff_q(channel_field="message__channel", date_field="message__date")

        top_emojis_qs = (
            MessageReaction.objects.filter(message__channel__in=in_target_pks, message__is_lost=False)
            .filter(cutoff_q)
            .values("emoji")
            .annotate(total=Sum("count"))
            .order_by("-total")[:8]
        )
        top_emojis = [r["emoji"] for r in top_emojis_qs]
        if not top_emojis:
            return JsonResponse({"labels": spine, "series": [], "y_label": "reactions"})

        monthly = (
            MessageReaction.objects.filter(
                message__channel__in=in_target_pks,
                message__date__isnull=False,
                message__is_lost=False,
                emoji__in=top_emojis,
            )
            .filter(cutoff_q)
            .annotate(month=TruncMonth("message__date"))
            .values("month", "emoji")
            .annotate(total=Sum("count"))
            .order_by("month", "emoji")
        )
        rows = [{"month": r["month"].strftime("%Y-%m"), "emoji": r["emoji"], "total": r["total"]} for r in monthly]
        df = pd.DataFrame(rows)
        if not df.empty:
            pivot = df.pivot_table(index="month", columns="emoji", values="total", aggfunc="sum", fill_value=0)
            pivot = pivot.reindex(spine, fill_value=0)
            pivot = pivot.reindex(columns=top_emojis, fill_value=0)
        else:
            pivot = pd.DataFrame(0, index=spine, columns=top_emojis)
            pivot.index.name = "month"

        series = [
            {"emoji": emoji_present(emoji), "values": [int(v) for v in pivot[emoji].tolist()]} for emoji in top_emojis
        ]
        return JsonResponse({"labels": spine, "series": series, "y_label": "reactions"})


class ChannelReactionsHistoryView(View):
    def get(self, request: HttpRequest, pk: int, *args: Any, **kwargs: Any) -> JsonResponse:
        channel = get_object_or_404(Channel, pk=pk)
        spine = channel_month_spine(channel)
        if not spine:
            return JsonResponse({"labels": [], "series": [], "y_label": "reactions"})

        top_emojis_filter = {"message__channel": channel, "message__is_lost": False}
        if channel.out_of_target_after:
            top_emojis_filter["message__date__date__lte"] = channel.out_of_target_after
        top_emojis_qs = (
            MessageReaction.objects.filter(**top_emojis_filter)
            .values("emoji")
            .annotate(total=Sum("count"))
            .order_by("-total")[:8]
        )
        top_emojis = [r["emoji"] for r in top_emojis_qs]
        if not top_emojis:
            return JsonResponse({"labels": spine, "series": [], "y_label": "reactions"})

        cutoff_kwargs = {"message__date__date__lte": channel.out_of_target_after} if channel.out_of_target_after else {}
        monthly = (
            MessageReaction.objects.filter(
                message__channel=channel,
                message__date__isnull=False,
                message__is_lost=False,
                emoji__in=top_emojis,
                **cutoff_kwargs,
            )
            .annotate(month=TruncMonth("message__date"))
            .values("month", "emoji")
            .annotate(total=Sum("count"))
            .order_by("month", "emoji")
        )
        rows = [{"month": r["month"].strftime("%Y-%m"), "emoji": r["emoji"], "total": r["total"]} for r in monthly]
        df = pd.DataFrame(rows)
        if not df.empty:
            pivot = df.pivot_table(index="month", columns="emoji", values="total", aggfunc="sum", fill_value=0)
            pivot = pivot.reindex(spine, fill_value=0)
            pivot = pivot.reindex(columns=top_emojis, fill_value=0)
        else:
            pivot = pd.DataFrame(0, index=spine, columns=top_emojis)
            pivot.index.name = "month"

        series = [
            {"emoji": emoji_present(emoji), "values": [int(v) for v in pivot[emoji].tolist()]} for emoji in top_emojis
        ]
        return JsonResponse({"labels": spine, "series": series, "y_label": "reactions"})


class ChannelTopMessagesView(View):
    """Top messages of a channel ranked by ``interest_score`` (Suh et al. 2010
    / Cha et al. 2010 weighted composite of per-channel z-scored views,
    forwards, reactions).

    Optionally merges in cross-community reach (C) and authority-weighted
    reach (D) from ``exports/<latest>/data/interest_structural.json`` when an
    export with that file is available.
    """

    _DEFAULT_LIMIT = 30
    _MAX_LIMIT = 100
    _PREVIEW_CHARS = 220

    def get(self, request: HttpRequest, pk: int, *args: Any, **kwargs: Any) -> JsonResponse:
        from django.db.models import F
        from django.urls import reverse

        # Local import to avoid the webapp ↔ stats import dance at module load.
        from webapp.views import _exclude_album_tails

        channel = get_object_or_404(Channel, pk=pk)
        try:
            limit = min(self._MAX_LIMIT, max(1, int(request.GET.get("limit", self._DEFAULT_LIMIT))))
        except (TypeError, ValueError):
            limit = self._DEFAULT_LIMIT

        qs = (
            Message.objects.alive()
            .filter(channel=channel, interest_score__isnull=False)
            .only(
                "pk",
                "telegram_id",
                "channel_id",
                "date",
                "message",
                "media_type",
                "grouped_id",
                "views",
                "forwards",
                "total_reactions",
                "interest_score",
                "z_views",
                "z_forwards",
                "z_reactions",
            )
        )
        if channel.out_of_target_after:
            qs = qs.filter(date__date__lte=channel.out_of_target_after)
        qs = _exclude_album_tails(qs).order_by(F("interest_score").desc(nulls_last=True), "-date", "-pk")[:limit]

        # Try to enrich with structural C/D from the latest published export.
        from webapp.utils.exports import latest_export_payload

        structural = latest_export_payload("interest_structural.json")
        by_message: dict[tuple[int, int], dict] = {}
        if structural is not None:
            for entry in structural.get("by_message") or ():
                key = (entry.get("channel_pk"), entry.get("telegram_id"))
                by_message[key] = entry

        messages = []
        for msg in qs:
            extra = by_message.get((msg.channel_id, msg.telegram_id), {})
            preview = (msg.message or "").strip().replace("\n", " ")
            if len(preview) > self._PREVIEW_CHARS:
                preview = preview[: self._PREVIEW_CHARS - 1].rstrip() + "…"
            messages.append(
                {
                    "telegram_id": msg.telegram_id,
                    "date": msg.date.isoformat() if msg.date else None,
                    "url": reverse(
                        "message-jump",
                        kwargs={"channel_pk": channel.pk, "telegram_id": msg.telegram_id},
                    ),
                    "preview": preview,
                    "media_type": msg.media_type or "",
                    "interest_score": msg.interest_score,
                    "z_views": msg.z_views,
                    "z_forwards": msg.z_forwards,
                    "z_reactions": msg.z_reactions,
                    "views": msg.views,
                    "forwards": msg.forwards,
                    "reactions": msg.total_reactions,
                    "c_cross_community": extra.get("c_cross_community"),
                    "d_authority_reach": extra.get("d_authority_reach"),
                }
            )

        from webapp.scoring import DEFAULT_WEIGHTS

        return JsonResponse(
            {
                "messages": messages,
                "structural_loaded": structural is not None,
                "structural_meta": (
                    {
                        "community_strategy": structural.get("community_strategy"),
                        "authority_key": structural.get("authority_key"),
                        "window_days": structural.get("window_days"),
                        "include_mentions": structural.get("include_mentions"),
                    }
                    if structural is not None
                    else None
                ),
                "weights": DEFAULT_WEIGHTS,
            }
        )


class ChannelContactInfoView(View):
    def get(self, request: HttpRequest, pk: int, *args: Any, **kwargs: Any) -> JsonResponse:
        channel = get_object_or_404(Channel, pk=pk)
        msg_qs = Message.objects.alive().filter(channel=channel)
        if channel.out_of_target_after:
            msg_qs = msg_qs.filter(date__date__lte=channel.out_of_target_after)
        texts = msg_qs.exclude(message__isnull=True).exclude(message="").values_list("message", flat=True)
        domain_counter: Counter = Counter()
        email_counter: Counter = Counter()
        for text in texts:
            for raw_host in _URL_RE.findall(text):
                host = raw_host.split(":")[0].lower().rstrip(".,;)")
                if host and host not in _TELEGRAM_HOSTS and not host.endswith(".telegram.org"):
                    domain_counter[host] += 1
            for email in _EMAIL_RE.findall(text):
                email_counter[email.lower()] += 1
        return JsonResponse(
            {
                "domains": [{"domain": d, "count": c} for d, c in domain_counter.most_common()],
                "emails": [{"email": e, "count": c} for e, c in email_counter.most_common()],
            }
        )
