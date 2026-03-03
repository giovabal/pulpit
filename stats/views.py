from math import pi
from typing import Any, ClassVar

from django.db.models import Count
from django.db.models.functions import TruncMonth
from django.http import HttpRequest, HttpResponse
from django.utils.decorators import method_decorator
from django.views import View
from django.views.decorators.clickjacking import xframe_options_sameorigin
from django.views.generic import TemplateView

from stats.mixins import StatsViewMixin
from webapp.mixins import BaseMixin
from webapp.models import Message

import pandas as pd
from bokeh.embed import file_html
from bokeh.models import HoverTool
from bokeh.plotting import figure
from bokeh.resources import CDN


class StatsPageView(BaseMixin, TemplateView):
    template_name = "stats/stats_page.html"


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

        line_options = self.base_line_options.copy()
        line_options.update({"width": 1, "source": df})
        figure_options = self.base_figure_options.copy()
        figure_options.update({"x_range": list(df.month.unique())})
        plot = figure(**figure_options, y_axis_label=self.y_label)
        plot.line("month", self.annotate_field, **line_options, legend_label=self.y_label)
        plot.legend.location = "top_left"
        plot.legend.click_policy = "hide"
        plot.xaxis.major_label_orientation = -pi / 4
        hover = plot.select({"type": HoverTool})
        hover.tooltips = [("", self.tooltip_template)]

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
