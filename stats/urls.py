from django.urls import path

from . import views

urlpatterns = [
    path("", views.StatsPageView.as_view(), name="stats-page"),
    path("data/messages_history/", views.MessagesHistoryDataView.as_view(), name="messages-history-data"),
]
