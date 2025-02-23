from .models import Channel


class BaseMixin:
    def get_context_data(self, *args, **kwargs):
        context_data = super().get_context_data(*args, **kwargs)
        context_data.update(
            {"channel_list": Channel.objects.filter(organization__is_interesting=True).order_by("title")}
        )

        return context_data
