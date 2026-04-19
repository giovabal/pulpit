from django.urls import path

from .views import EventsDataView

urlpatterns = [
    path("data/events/", EventsDataView.as_view(), name="events-data"),
]
