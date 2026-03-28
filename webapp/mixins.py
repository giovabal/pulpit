from typing import Any

from django.db.models import Count

from .models import Channel


class BaseMixin:
    def get_context_data(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
        context_data: dict[str, Any] = super().get_context_data(*args, **kwargs)  # type: ignore[misc]
        context_data.update(
            {
                "channel_list": Channel.objects.interesting()
                .select_related("organization")
                .annotate(messages_count=Count("message_set"))
                .order_by("title")
            }
        )
        return context_data
