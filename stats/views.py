from math import pi

from django.db.models import Count
from django.db.models.functions import TruncMonth
from django.http import HttpResponse
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
class MessagesHistoryDataView(StatsViewMixin, View):
    def get(self, request, *args, **kwargs):
        monthly_totals = (
            Message.objects.filter(channel__organization__is_interesting=True, date__isnull=False)
            .annotate(month=TruncMonth("date"))
            .values("month")
            .annotate(total_messages=Count("id"))
            .order_by("month")
        )

        df = pd.DataFrame(
            [
                {"month": entry["month"].strftime("%Y-%m"), "total_messages": entry["total_messages"]}
                for entry in monthly_totals
            ]
        )

        line_options = self.base_line_options.copy()
        line_options.update({"width": 1, "source": df})
        figure_options = self.base_figure_options.copy()
        figure_options.update({"x_range": list(df.month.unique())})
        plot = figure(
            **figure_options,
            y_axis_label="messages",
        )
        plot.line("month", "total_messages", **line_options, legend_label="messages")
        plot.legend.location = "top_left"
        plot.legend.click_policy = "hide"
        plot.xaxis.major_label_orientation = -pi / 4
        hover = plot.select({"type": HoverTool})
        hover.tooltips = [("", "@month: @total_messages messages")]

        html = file_html(plot, CDN, "Messages history")
        return HttpResponse(html)
