from typing import Any

from django.db.models import QuerySet
from django.http import HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404
from django.views.generic import ListView, TemplateView

from webapp_engine.paginator import DiggPaginator

from .mixins import BaseMixin
from .models import Channel, Message


class HomeView(BaseMixin, TemplateView):
    template_name = "webapp/home.html"


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
        context_data = super().get_context_data(*args, **kwargs)
        context_data.update({"selected_channel": self.selected_channel})
        return context_data
