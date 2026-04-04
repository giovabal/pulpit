from typing import Any, ClassVar

from django.db import models
from django.db.models import Avg, Count, Sum
from django.db.models.functions import TruncMonth
from django.http import HttpRequest, JsonResponse
from django.shortcuts import get_object_or_404
from django.views import View

from stats.queries import channel_month_spine, global_month_spine, reindex_to_spine
from webapp.models import Channel, Message

import pandas as pd


class _GlobalTimeSeriesBase(View):
    annotate_field: ClassVar[str]
    y_label: ClassVar[str]

    def get_annotation(self) -> Count | Sum | Avg:
        raise NotImplementedError

    def get(self, request: HttpRequest, *args: Any, **kwargs: Any) -> JsonResponse:
        spine = global_month_spine()
        if not spine:
            return JsonResponse({"labels": [], "values": [], "y_label": self.y_label})

        monthly_data = (
            Message.objects.filter(channel__organization__is_interesting=True, date__isnull=False)
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


class SubscribersHistoryDataView(View):
    def get(self, request: HttpRequest, *args: Any, **kwargs: Any) -> JsonResponse:
        spine = global_month_spine()
        if not spine:
            return JsonResponse({"labels": [], "values": [], "y_label": "total subscribers"})
        channels = (
            Channel.objects.filter(organization__is_interesting=True, participants_count__isnull=False)
            .annotate(first_message=models.Min("message_set__date"))
            .filter(first_message__isnull=False)
            .values("participants_count", "first_message")
        )
        df = pd.DataFrame(
            [
                {
                    "month": entry["first_message"].strftime("%Y-%m"),
                    "participants_count": entry["participants_count"],
                }
                for entry in channels
            ]
        )
        if df.empty:
            return JsonResponse({"labels": spine, "values": [0] * len(spine), "y_label": "total subscribers"})
        monthly = df.groupby("month")["participants_count"].sum().reset_index()
        monthly = monthly.sort_values("month")
        monthly["cumulative"] = monthly["participants_count"].cumsum()
        monthly = (
            monthly.set_index("month")[["cumulative"]]
            .reindex(spine)
            .ffill()
            .fillna(0)
            .astype(int)
            .reset_index()
            .rename(columns={"index": "month"})
        )
        return JsonResponse(
            {
                "labels": list(monthly["month"]),
                "values": list(monthly["cumulative"]),
                "y_label": "total subscribers",
            }
        )


class _ChannelTimeSeriesBase(View):
    annotate_field: ClassVar[str]
    y_label: ClassVar[str]

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
            Message.objects.filter(channel=channel, date__isnull=False)
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
            Message.objects.filter(channel=channel, date__isnull=False, views__isnull=False)
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
            Message.objects.filter(channel=channel, date__isnull=False, forwarded_from__isnull=False)
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
        qs = (
            Message.objects.filter(
                channel__organization__is_interesting=True,
                forwarded_from=channel,
                date__isnull=False,
            )
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
            Message.objects.filter(channel=channel, date__isnull=False)
            .annotate(month=TruncMonth("date"))
            .values("month")
            .annotate(avg_involvement=Avg("views", default=0))
            .order_by("month")
        )
        return [{"month": e["month"].strftime("%Y-%m"), "avg_involvement": round(e["avg_involvement"])} for e in qs]
