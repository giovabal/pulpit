import re
from collections import Counter
from typing import Any, ClassVar

from django.db import models
from django.db.models import Avg, Count, Max, Min, Sum
from django.db.models.functions import TruncMonth
from django.http import HttpRequest, JsonResponse
from django.shortcuts import get_object_or_404
from django.utils import timezone
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
        """Base Message queryset for a channel, restricted to its in-target periods and excluding lost."""
        from network.utils import channel_period_date_q

        qs = Message.objects.alive().filter(channel=channel, **filters)
        if channel.in_target_periods.exists():
            qs = qs.filter(channel_period_date_q(channel))
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

    def get_spine(self, channel: Channel) -> list[str]:
        """Month spine the data are reindexed to. Default: the channel's own posting
        span. Views whose data come from *other* channels' messages must override
        this — ``reindex_to_spine`` drops any bucket outside the spine."""
        return channel_month_spine(channel)

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
        spine = self.get_spine(channel)
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

    def get_spine(self, channel: Channel) -> list[str]:
        """Span the union of the channel's own months and the forwards' months.

        The data here are *other* channels' forwards, which can occur after the
        subject's last own post (post-closure amplification — exactly what the
        vacancy analysis studies) or when the subject has no alive posts at all;
        the default own-months spine would silently drop those buckets.
        """
        own = channel_month_spine(channel)
        agg = self.get_queryset(channel).aggregate(earliest=Min("date"), latest=Max("date"))
        if not agg["earliest"]:
            return own
        fwd_first = timezone.localtime(agg["earliest"]).strftime("%Y-%m")
        fwd_last = timezone.localtime(agg["latest"]).strftime("%Y-%m")
        start = min(own[0], fwd_first) if own else fwd_first
        end = max(own[-1], fwd_last) if own else fwd_last
        return pd.period_range(start=start, end=end, freq="M").strftime("%Y-%m").tolist()

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
            # Like the other three legs: the subject must not list itself.
            .exclude(channel=channel)
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

        from network.utils import channel_period_date_q

        period_q = channel_period_date_q(channel, "message__date") if channel.in_target_periods.exists() else None
        top_emojis_qs = MessageReaction.objects.filter(message__channel=channel, message__is_lost=False)
        if period_q is not None:
            top_emojis_qs = top_emojis_qs.filter(period_q)
        top_emojis_qs = top_emojis_qs.values("emoji").annotate(total=Sum("count")).order_by("-total")[:8]
        top_emojis = [r["emoji"] for r in top_emojis_qs]
        if not top_emojis:
            return JsonResponse({"labels": spine, "series": [], "y_label": "reactions"})

        monthly_qs = MessageReaction.objects.filter(
            message__channel=channel,
            message__date__isnull=False,
            message__is_lost=False,
            emoji__in=top_emojis,
        )
        if period_q is not None:
            monthly_qs = monthly_qs.filter(period_q)
        monthly = (
            monthly_qs.annotate(month=TruncMonth("message__date"))
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


class ChannelContactInfoView(View):
    def get(self, request: HttpRequest, pk: int, *args: Any, **kwargs: Any) -> JsonResponse:
        channel = get_object_or_404(Channel, pk=pk)
        msg_qs = Message.objects.alive().filter(channel=channel)
        if channel.in_target_periods.exists():
            from network.utils import channel_period_date_q

            msg_qs = msg_qs.filter(channel_period_date_q(channel))
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
