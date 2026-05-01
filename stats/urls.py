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
    path(
        "data/avg_involvement_history/",
        views.AvgInvolvementHistoryDataView.as_view(),
        name="avg-involvement-history-data",
    ),
    path(
        "data/channel/<int:pk>/avg_involvement_history/",
        views.ChannelAvgInvolvementHistoryView.as_view(),
        name="channel-avg-involvement-history",
    ),
    path(
        "data/channel/<int:pk>/cross_refs/",
        views.ChannelCrossRefsView.as_view(),
        name="channel-cross-refs",
    ),
    path(
        "data/channel/<int:pk>/contact_info/",
        views.ChannelContactInfoView.as_view(),
        name="channel-contact-info",
    ),
    path(
        "data/channel/<int:pk>/reactions_history/",
        views.ChannelReactionsHistoryView.as_view(),
        name="channel-reactions-history",
    ),
]
