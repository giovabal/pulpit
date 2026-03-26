from typing import Any

from django.db.models import Max, Min, QuerySet, Sum
from django.http import HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404
from django.views.generic import ListView, TemplateView

from webapp.paginator import DiggPaginator

from .mixins import BaseMixin
from .models import Channel, Message
from .utils.dates import fmt_date


class HomeView(BaseMixin, TemplateView):
    template_name = "webapp/home.html"

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:
        from django.urls import reverse

        ctx = super().get_context_data(**kwargs)

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

        ctx["summary"] = [
            {
                "icon": "bi-broadcast",
                "label": "Channels",
                "value": f"{interesting_channels:,}",
            },
            {"icon": "bi-chat-left-text", "label": "Messages collected", "value": f"{total_messages:,}"},
            {"icon": "bi-people", "label": "Total subscribers", "value": f"{total_subscribers:,}"},
            {
                "icon": "bi-calendar-range",
                "label": "Date range",
                "value": f"{fmt_date(date_agg['earliest'])} – {fmt_date(date_agg['latest'])}",
                "note": "first message - last message",
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
            {"id": "views-history", "title": "Views per month", "icon": "bi-eye", "url": reverse("views-history-data")},
            {
                "id": "subscribers-history",
                "title": "Cumulative subscribers",
                "icon": "bi-people",
                "url": reverse("subscribers-history-data"),
            },
            {
                "id": "avg-involvement-history",
                "title": "Average involvement per month",
                "icon": "bi-graph-up",
                "url": reverse("avg-involvement-history-data"),
            },
        ]
        return ctx


class MessageSearchView(BaseMixin, ListView):
    template_name = "webapp/message_search.html"
    model = Message
    paginator_class = DiggPaginator
    paginate_by = 50
    paginate_orphans = 15
    page_kwarg = "page"

    def get_queryset(self, *args: Any, **kwargs: Any) -> QuerySet[Message]:
        qs = (
            Message.objects.filter(channel__organization__is_interesting=True)
            .select_related("channel", "channel__organization", "forwarded_from")
            .order_by("-date")
        )
        q = self.request.GET.get("q", "").strip()
        if q:
            qs = qs.filter(message__icontains=q)
        return qs

    def get_context_data(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
        context_data = super().get_context_data(*args, **kwargs)
        q = self.request.GET.get("q", "").strip()
        context_data["query"] = q
        context_data["original_query"] = f"&q={q}" if q else ""
        return context_data


class ChannelDetailView(BaseMixin, ListView):
    template_name = "webapp/channel_detail.html"
    model = Message
    paginator_class = DiggPaginator
    paginate_by = 50
    paginate_orphans = 15
    page_kwarg = "page"

    def get(self, request: HttpRequest, *args: Any, **kwargs: Any) -> HttpResponse:
        self.selected_channel = get_object_or_404(Channel, pk=kwargs.get("pk"))
        return super().get(request, *args, **kwargs)

    def get_queryset(self, *args: Any, **kwargs: Any) -> QuerySet[Message]:
        qs = super().get_queryset(*args, **kwargs)
        return (
            qs.filter(channel=self.selected_channel).prefetch_related("references", "forwarded_from").order_by("date")
        )

    def get_context_data(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
        from django.urls import reverse

        context_data = super().get_context_data(*args, **kwargs)
        ch = self.selected_channel

        msg_qs = Message.objects.filter(channel=ch)
        total_messages = msg_qs.count()
        total_views = msg_qs.aggregate(total=Sum("views"))["total"] or 0
        total_forwards_sent = msg_qs.filter(forwarded_from__isnull=False).count()
        total_forwards_received = Message.objects.filter(
            channel__organization__is_interesting=True, forwarded_from=ch
        ).count()
        date_agg = msg_qs.filter(date__isnull=False).aggregate(earliest=Min("date"), latest=Max("date"))

        summary = [
            {"icon": "bi-chat-left-text", "label": "Messages", "value": f"{total_messages:,}"},
            {"icon": "bi-eye", "label": "Total views", "value": f"{total_views:,}"},
            {
                "icon": "bi-calendar-range",
                "label": "Date range",
                "value": f"{fmt_date(date_agg['earliest'])} – {fmt_date(date_agg['latest'])}",
            },
            {
                "icon": "bi-forward",
                "label": "Forwards sent",
                "value": f"{total_forwards_sent:,}",
                "note": "to other channels",
            },
            {
                "icon": "bi-arrow-return-right",
                "label": "Forwards received",
                "value": f"{total_forwards_received:,}",
                "note": "from other channels",
            },
        ]

        panels = [
            {
                "id": "ch-messages-history",
                "title": "Messages per month",
                "icon": "bi-bar-chart-line",
                "url": reverse("channel-messages-history", kwargs={"pk": ch.pk}),
            },
            {
                "id": "ch-views-history",
                "title": "Views per month",
                "icon": "bi-eye",
                "url": reverse("channel-views-history", kwargs={"pk": ch.pk}),
            },
            {
                "id": "ch-forwards-history",
                "title": "Forwards sent per month",
                "icon": "bi-forward",
                "url": reverse("channel-forwards-history", kwargs={"pk": ch.pk}),
            },
            {
                "id": "ch-forwards-received-history",
                "title": "Forwards received per month",
                "icon": "bi-arrow-return-right",
                "url": reverse("channel-forwards-received-history", kwargs={"pk": ch.pk}),
            },
            {
                "id": "ch-avg-involvement-history",
                "title": "Average involvement per month",
                "icon": "bi-graph-up",
                "url": reverse("channel-avg-involvement-history", kwargs={"pk": ch.pk}),
            },
        ]

        context_data.update({"selected_channel": ch, "summary": summary, "panels": panels})
        return context_data
