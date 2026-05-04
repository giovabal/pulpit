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

        interesting_pks = Channel.objects.interesting().values("pk")
        monthly_data = (
            Message.objects.filter(channel__in=interesting_pks, date__isnull=False)
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
    annotate_field: ClassVar[str]
    y_label: ClassVar[str]

    def _msg_qs(self, channel: Channel, **filters):
        """Base Message queryset for a channel, respecting uninteresting_after."""
        qs = Message.objects.filter(channel=channel, **filters)
        if channel.uninteresting_after:
            qs = qs.filter(date__date__lte=channel.uninteresting_after)
        return qs

    def _get_monthly_data(self, channel: Channel) -> list[dict]:
        raise NotImplementedError

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

    def _get_monthly_data(self, channel: Channel) -> list[dict]:
        qs = (
            self._msg_qs(channel, date__isnull=False)
            .annotate(month=TruncMonth("date"))
            .values("month")
            .annotate(total_messages=Count("id"))
            .order_by("month")
        )
        return [{"month": e["month"].strftime("%Y-%m"), "total_messages": e["total_messages"]} for e in qs]


class ChannelViewsHistoryView(_ChannelTimeSeriesBase):
    annotate_field = "total_views"
    y_label = "views"

    def _get_monthly_data(self, channel: Channel) -> list[dict]:
        qs = (
            self._msg_qs(channel, date__isnull=False, views__isnull=False)
            .annotate(month=TruncMonth("date"))
            .values("month")
            .annotate(total_views=Sum("views"))
            .order_by("month")
        )
        return [{"month": e["month"].strftime("%Y-%m"), "total_views": e["total_views"]} for e in qs]


class ChannelForwardsHistoryView(_ChannelTimeSeriesBase):
    annotate_field = "total_forwards"
    y_label = "forwards sent"

    def _get_monthly_data(self, channel: Channel) -> list[dict]:
        qs = (
            self._msg_qs(channel, date__isnull=False, forwarded_from__isnull=False)
            .annotate(month=TruncMonth("date"))
            .values("month")
            .annotate(total_forwards=Count("id"))
            .order_by("month")
        )
        return [{"month": e["month"].strftime("%Y-%m"), "total_forwards": e["total_forwards"]} for e in qs]


class ChannelForwardsReceivedHistoryView(_ChannelTimeSeriesBase):
    annotate_field = "total_forwards_received"
    y_label = "forwards received"

    def _get_monthly_data(self, channel: Channel) -> list[dict]:
        interesting_pks = Channel.objects.interesting().values("pk")
        from network.utils import channel_cutoff_q

        qs = (
            Message.objects.filter(
                channel__in=interesting_pks,
                forwarded_from=channel,
                date__isnull=False,
            )
            .filter(channel_cutoff_q())
            .annotate(month=TruncMonth("date"))
            .values("month")
            .annotate(total_forwards_received=Count("id"))
            .order_by("month")
        )
        return [
            {"month": e["month"].strftime("%Y-%m"), "total_forwards_received": e["total_forwards_received"]} for e in qs
        ]


class ChannelAvgInvolvementHistoryView(_ChannelTimeSeriesBase):
    annotate_field = "avg_involvement"
    y_label = "avg views"

    def _get_monthly_data(self, channel: Channel) -> list[dict]:
        qs = (
            self._msg_qs(channel, date__isnull=False)
            .annotate(month=TruncMonth("date"))
            .values("month")
            .annotate(avg_involvement=Avg("views", default=0))
            .order_by("month")
        )
        return [{"month": e["month"].strftime("%Y-%m"), "avg_involvement": round(e["avg_involvement"])} for e in qs]


class ChannelCrossRefsView(View):
    def get(self, request: HttpRequest, pk: int, *args: Any, **kwargs: Any) -> JsonResponse:
        channel = get_object_or_404(Channel, pk=pk)
        interesting_pks = Channel.objects.interesting().values("pk")

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
            Message.objects.filter(channel__in=interesting_pks, forwarded_from=channel)
            .filter(channel_cutoff_q())
            .values_list("channel", flat=True)
        )
        ref_in = Counter(
            Message.objects.filter(channel__in=interesting_pks, references=channel)
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


class ChannelReactionsHistoryView(View):
    def get(self, request: HttpRequest, pk: int, *args: Any, **kwargs: Any) -> JsonResponse:
        channel = get_object_or_404(Channel, pk=pk)
        spine = channel_month_spine(channel)
        if not spine:
            return JsonResponse({"labels": [], "series": [], "y_label": "reactions"})

        top_emojis_filter = {"message__channel": channel}
        if channel.uninteresting_after:
            top_emojis_filter["message__date__date__lte"] = channel.uninteresting_after
        top_emojis_qs = (
            MessageReaction.objects.filter(**top_emojis_filter)
            .values("emoji")
            .annotate(total=Sum("count"))
            .order_by("-total")[:8]
        )
        top_emojis = [r["emoji"] for r in top_emojis_qs]
        if not top_emojis:
            return JsonResponse({"labels": spine, "series": [], "y_label": "reactions"})

        cutoff_kwargs = {"message__date__date__lte": channel.uninteresting_after} if channel.uninteresting_after else {}
        monthly = (
            MessageReaction.objects.filter(
                message__channel=channel,
                message__date__isnull=False,
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

        series = [{"emoji": emoji, "values": [int(v) for v in pivot[emoji].tolist()]} for emoji in top_emojis]
        return JsonResponse({"labels": spine, "series": series, "y_label": "reactions"})


class ChannelContactInfoView(View):
    def get(self, request: HttpRequest, pk: int, *args: Any, **kwargs: Any) -> JsonResponse:
        channel = get_object_or_404(Channel, pk=pk)
        msg_qs = Message.objects.filter(channel=channel)
        if channel.uninteresting_after:
            msg_qs = msg_qs.filter(date__date__lte=channel.uninteresting_after)
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
