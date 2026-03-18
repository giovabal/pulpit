from django.urls import path

from . import views

urlpatterns = [
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
    path(
        "data/channel/<int:pk>/views_history/",
        views.ChannelViewsHistoryView.as_view(),
        name="channel-views-history",
    ),
    path(
        "data/channel/<int:pk>/forwards_history/",
        views.ChannelForwardsHistoryView.as_view(),
        name="channel-forwards-history",
    ),
    path(
        "data/channel/<int:pk>/forwards_received_history/",
        views.ChannelForwardsReceivedHistoryView.as_view(),
        name="channel-forwards-received-history",
    ),
    path("data/forwards_history/", views.ForwardsHistoryDataView.as_view(), name="forwards-history-data"),
    path("data/views_history/", views.ViewsHistoryDataView.as_view(), name="views-history-data"),
    path("data/subscribers_history/", views.SubscribersHistoryDataView.as_view(), name="subscribers-history-data"),
]
