from django.http import JsonResponse
from django.views import View

from .models import Event


class EventsDataView(View):
    def get(self, request):
        events = Event.objects.select_related("action").order_by("date")
        data = [
            {
                "date": str(e.date),
                "subject": e.subject,
                "action": e.action.name,
                "color": e.action.color,
            }
            for e in events
        ]
        return JsonResponse(data, safe=False)
