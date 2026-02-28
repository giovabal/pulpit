from django.db.models import Count
from django.db.models.functions import TruncMonth
from django.http import HttpResponse
from django.utils.decorators import method_decorator
from django.views import View
from django.views.decorators.clickjacking import xframe_options_sameorigin
from django.views.generic import TemplateView

from webapp.mixins import BaseMixin
from webapp.models import Message

from bokeh.embed import file_html
from bokeh.plotting import figure
from bokeh.resources import CDN


class StatsPageView(BaseMixin, TemplateView):
    template_name = "stats/stats_page.html"


@method_decorator(xframe_options_sameorigin, name="dispatch")
class MessagesHistoryDataView(View):
    def get(self, request, *args, **kwargs):
        monthly_totals = (
            Message.objects.filter(channel__organization__is_interesting=True, date__isnull=False)
            .annotate(month=TruncMonth("date"))
            .values("month")
            .annotate(total_messages=Count("id"))
            .order_by("month")
        )

        months = [entry["month"].strftime("%Y-%m") for entry in monthly_totals]
        totals = [entry["total_messages"] for entry in monthly_totals]

        plot = figure(
            x_range=months,
            title="Monthly total messages from interesting channels",
            x_axis_label="Month",
            y_axis_label="Total messages",
            width=1000,
            height=450,
            toolbar_location="above",
        )
        plot.vbar(x=months, top=totals, width=0.8)
        plot.xaxis.major_label_orientation = 0.8

        html = file_html(plot, CDN, "Messages history")
        return HttpResponse(html)
