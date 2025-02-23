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
    paginate_by = 100
    paginate_orphans = 20
    page_kwarg = "pagina"

    def get(self, request, *args, **kwargs):
        self.selected_channel = Channel.objects.get(pk=kwargs.get("pk"))
        return super().get(request, *args, **kwargs)

    def get_context_data(self, *args, **kwargs):
        context_data = super().get_context_data(*args, **kwargs)
        context_data.update(
            {
                "selected_channel": self.selected_channel,
                "message_list": Message.objects.filter(channel=self.selected_channel).order_by("date"),
            }
        )
        print(context_data)

        return context_data
