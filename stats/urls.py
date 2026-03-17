from django.urls import path

from . import views

urlpatterns = [
    path("", views.StatsPageView.as_view(), name="stats-page"),
    path("data/messages_history/", views.MessagesHistoryDataView.as_view(), name="messages-history-data"),
    path(
        "data/active_channels_history/",
        views.ActiveChannelsHistoryDataView.as_view(),
        name="active-channels-history-data",
    ),
    path(
        "data/channel/<int:pk>/messages_history/",
        views.ChannelMessagesHistoryView.as_view(),
        name="channel-messages-history",
    ),
]
