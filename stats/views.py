from math import pi
from typing import Any, ClassVar

from django.db import models
from django.db.models import Count, Max, Min, Sum
from django.db.models.functions import TruncMonth
from django.http import HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404
from django.utils.decorators import method_decorator
from django.views import View
from django.views.decorators.clickjacking import xframe_options_sameorigin
from django.views.generic import TemplateView

from stats.mixins import StatsViewMixin
from webapp.mixins import BaseMixin
from webapp.models import Channel, Message

import pandas as pd
from bokeh.embed import file_html
from bokeh.models import HoverTool
from bokeh.plotting import figure
from bokeh.resources import CDN


class StatsPageView(BaseMixin, TemplateView):
    template_name = "stats/stats_page.html"

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:
        from django.urls import reverse

        ctx = super().get_context_data(**kwargs)

        total_channels = Channel.objects.count()
        interesting_channels = Channel.objects.filter(organization__is_interesting=True).count()
        total_messages = Message.objects.count()
        total_subscribers = (
            Channel.objects.filter(organization__is_interesting=True, participants_count__isnull=False).aggregate(
                total=Sum("participants_count")
            )["total"]
            or 0
        )
        date_agg = Message.objects.filter(date__isnull=False).aggregate(earliest=Min("date"), latest=Max("date"))
        total_forwards = Message.objects.filter(forwarded_from__isnull=False).count()

        def fmt_date(d: Any) -> str:
            return d.strftime("%b %Y") if d else "—"

        ctx["summary"] = [
            {
                "icon": "bi-broadcast",
                "label": "Channels",
                "value": f"{interesting_channels:,} / {total_channels:,}",
                "note": "interesting / total",
            },
            {"icon": "bi-chat-left-text", "label": "Messages collected", "value": f"{total_messages:,}"},
            {"icon": "bi-people", "label": "Total subscribers", "value": f"{total_subscribers:,}"},
            {
                "icon": "bi-calendar-range",
                "label": "Date range",
                "value": f"{fmt_date(date_agg['earliest'])} – {fmt_date(date_agg['latest'])}",
            },
            {
                "icon": "bi-forward",
                "label": "Forwards",
                "value": f"{total_forwards:,}",
                "note": "cross-channel amplifications",
            },
        ]
        ctx["panels"] = [
            {
                "id": "messages-history",
                "title": "Messages per month",
                "icon": "bi-bar-chart-line",
                "url": reverse("messages-history-data"),
            },
            {
                "id": "active-channels-history",
                "title": "Active channels per month",
                "icon": "bi-broadcast",
                "url": reverse("active-channels-history-data"),
            },
            {
                "id": "forwards-history",
                "title": "Forwards per month",
                "icon": "bi-forward",
                "url": reverse("forwards-history-data"),
            },
            {
                "id": "views-history",
                "title": "Views per month",
                "icon": "bi-eye",
                "url": reverse("views-history-data"),
            },
            {
                "id": "subscribers-history",
                "title": "Cumulative subscribers",
                "icon": "bi-people",
                "url": reverse("subscribers-history-data"),
            },
        ]
        return ctx


@method_decorator(xframe_options_sameorigin, name="dispatch")
class TimeSeriesChartView(StatsViewMixin, View):
    annotate_field: ClassVar[str]
    y_label: ClassVar[str]
    chart_title: ClassVar[str]
    tooltip_template: ClassVar[str]

    def get_annotation(self) -> Count:
        raise NotImplementedError

    def get(self, request: HttpRequest, *args: Any, **kwargs: Any) -> HttpResponse:
        monthly_data = (
            Message.objects.filter(channel__organization__is_interesting=True, date__isnull=False)
            .annotate(month=TruncMonth("date"))
            .values("month")
            .annotate(**{self.annotate_field: self.get_annotation()})
            .order_by("month")
        )

        df = pd.DataFrame(
            [
                {"month": entry["month"].strftime("%Y-%m"), self.annotate_field: entry[self.annotate_field]}
                for entry in monthly_data
            ]
        )

        figure_options = self.base_figure_options.copy()
        figure_options.update({"x_range": list(df.month.unique())})
        plot = figure(**figure_options, y_axis_label=self.y_label)
        plot.vbar(
            x="month",
            top=self.annotate_field,
            source=df,
            width=0.7,
            fill_color="#2563eb",
            fill_alpha=0.75,
            line_color=None,
        )
        plot.xaxis.major_label_orientation = -pi / 4
        self._style_plot(plot)
        hover = plot.select({"type": HoverTool})
        hover.tooltips = (
            f'<span style="font-family:Inter,system-ui,sans-serif;font-size:12px">{self.tooltip_template}</span>'
        )

        html = file_html(plot, CDN, self.chart_title)
        return HttpResponse(html)


class MessagesHistoryDataView(TimeSeriesChartView):
    annotate_field = "total_messages"
    y_label = "messages"
    chart_title = "Messages history"
    tooltip_template = "@month: @total_messages messages"

    def get_annotation(self) -> Count:
        return Count("id")


class ActiveChannelsHistoryDataView(TimeSeriesChartView):
    annotate_field = "total_active_channels"
    y_label = "active channels"
    chart_title = "Active channels history"
    tooltip_template = "@month: @total_active_channels active channels"

    def get_annotation(self) -> Count:
        return Count("channel", distinct=True)


class ForwardsHistoryDataView(TimeSeriesChartView):
    annotate_field = "total_forwards"
    y_label = "forwards"
    chart_title = "Forwards history"
    tooltip_template = "@month: @total_forwards forwards"

    def get_annotation(self) -> Count:
        return Count("id", filter=models.Q(forwarded_from__isnull=False))


class ViewsHistoryDataView(TimeSeriesChartView):
    annotate_field = "total_views"
    y_label = "views"
    chart_title = "Views history"
    tooltip_template = "@month: @total_views views"

    def get_annotation(self) -> Sum:
        return Sum("views", default=0)


@method_decorator(xframe_options_sameorigin, name="dispatch")
class ChannelMessagesHistoryView(StatsViewMixin, View):
    def get(self, request: HttpRequest, pk: int, *args: Any, **kwargs: Any) -> HttpResponse:
        channel = get_object_or_404(Channel, pk=pk)
        monthly_data = (
            Message.objects.filter(channel=channel, date__isnull=False)
            .annotate(month=TruncMonth("date"))
            .values("month")
            .annotate(total_messages=Count("id"))
            .order_by("month")
        )

        df = pd.DataFrame(
            [
                {"month": entry["month"].strftime("%Y-%m"), "total_messages": entry["total_messages"]}
                for entry in monthly_data
            ]
        )

        if df.empty:
            return HttpResponse(
                "<html><body style='font-family:sans-serif;color:#9ca3af;"
                "display:flex;align-items:center;justify-content:center;height:100%;margin:0;'>"
                "<p>No data available</p></body></html>"
            )

        figure_options = self.base_figure_options.copy()
        figure_options.update({"height": 300, "x_range": list(df.month.unique())})

        plot = figure(**figure_options, y_axis_label="messages")
        plot.vbar(
            x="month",
            top="total_messages",
            source=df,
            width=0.7,
            fill_color="#2563eb",
            fill_alpha=0.75,
            line_color=None,
        )
        plot.xaxis.major_label_orientation = -pi / 4
        self._style_plot(plot)
        hover = plot.select({"type": HoverTool})
        hover.tooltips = '<span style="font-family:Inter,system-ui,sans-serif;font-size:12px">@month &nbsp; <strong>@total_messages</strong></span>'

        html = file_html(plot, CDN, f"{channel.title} – message history")
        return HttpResponse(html)


class _ChannelTimeSeriesBase(StatsViewMixin, View):
    """Base for per-channel monthly vbar charts."""

    chart_title_suffix: ClassVar[str]
    annotate_field: ClassVar[str]
    y_label: ClassVar[str]
    tooltip_template: ClassVar[str]

    def _get_monthly_data(self, channel: Channel) -> list[dict]:
        raise NotImplementedError

    def get(self, request: HttpRequest, pk: int, *args: Any, **kwargs: Any) -> HttpResponse:
        channel = get_object_or_404(Channel, pk=pk)
        rows = self._get_monthly_data(channel)
        df = pd.DataFrame(rows)

        if df.empty:
            return HttpResponse(
                "<html><body style='font-family:sans-serif;color:#9ca3af;"
                "display:flex;align-items:center;justify-content:center;height:100%;margin:0;'>"
                "<p>No data available</p></body></html>"
            )

        figure_options = self.base_figure_options.copy()
        figure_options.update({"height": 300, "x_range": list(df.month.unique())})
        plot = figure(**figure_options, y_axis_label=self.y_label)
        plot.vbar(
            x="month",
            top=self.annotate_field,
            source=df,
            width=0.7,
            fill_color="#2563eb",
            fill_alpha=0.75,
            line_color=None,
        )
        plot.xaxis.major_label_orientation = -pi / 4
        self._style_plot(plot)
        hover = plot.select({"type": HoverTool})
        hover.tooltips = (
            f'<span style="font-family:Inter,system-ui,sans-serif;font-size:12px">{self.tooltip_template}</span>'
        )
        html = file_html(plot, CDN, f"{channel.title} – {self.chart_title_suffix}")
        return HttpResponse(html)


@method_decorator(xframe_options_sameorigin, name="dispatch")
class ChannelViewsHistoryView(_ChannelTimeSeriesBase):
    chart_title_suffix = "views history"
    annotate_field = "total_views"
    y_label = "views"
    tooltip_template = "@month &nbsp; <strong>@total_views{0,0}</strong> views"

    def _get_monthly_data(self, channel: Channel) -> list[dict]:
        qs = (
            Message.objects.filter(channel=channel, date__isnull=False, views__isnull=False)
            .annotate(month=TruncMonth("date"))
            .values("month")
            .annotate(total_views=Sum("views"))
            .order_by("month")
        )
        return [{"month": e["month"].strftime("%Y-%m"), "total_views": e["total_views"]} for e in qs]


@method_decorator(xframe_options_sameorigin, name="dispatch")
class ChannelForwardsHistoryView(_ChannelTimeSeriesBase):
    chart_title_suffix = "forwards sent history"
    annotate_field = "total_forwards"
    y_label = "forwards sent"
    tooltip_template = "@month &nbsp; <strong>@total_forwards</strong> forwards sent"

    def _get_monthly_data(self, channel: Channel) -> list[dict]:
        qs = (
            Message.objects.filter(channel=channel, date__isnull=False, forwarded_from__isnull=False)
            .annotate(month=TruncMonth("date"))
            .values("month")
            .annotate(total_forwards=Count("id"))
            .order_by("month")
        )
        return [{"month": e["month"].strftime("%Y-%m"), "total_forwards": e["total_forwards"]} for e in qs]


@method_decorator(xframe_options_sameorigin, name="dispatch")
class SubscribersHistoryDataView(StatsViewMixin, View):
    def get(self, request: HttpRequest, *args: Any, **kwargs: Any) -> HttpResponse:
        # For each interesting channel with a known participant count, find the month
        # of its earliest message and treat that as its "entry month".
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
            return HttpResponse(
                "<html><body style='font-family:sans-serif;color:#9ca3af;"
                "display:flex;align-items:center;justify-content:center;height:100%;margin:0;'>"
                "<p>No data available</p></body></html>"
            )

        monthly = df.groupby("month")["participants_count"].sum().reset_index()
        monthly = monthly.sort_values("month")
        monthly["cumulative"] = monthly["participants_count"].cumsum()

        figure_options = self.base_figure_options.copy()
        figure_options.update({"x_range": list(monthly["month"])})
        plot = figure(**figure_options, y_axis_label="total subscribers")
        plot.vbar(
            x="month",
            top="cumulative",
            source=monthly,
            width=0.7,
            fill_color="#2563eb",
            fill_alpha=0.75,
            line_color=None,
        )
        plot.xaxis.major_label_orientation = -pi / 4
        self._style_plot(plot)
        hover = plot.select({"type": HoverTool})
        hover.tooltips = (
            '<span style="font-family:Inter,system-ui,sans-serif;font-size:12px">'
            "@month &nbsp; <strong>@cumulative{0,0}</strong> subscribers</span>"
        )

        html = file_html(plot, CDN, "Cumulative subscribers history")
        return HttpResponse(html)
