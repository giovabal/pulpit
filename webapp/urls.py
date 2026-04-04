from django.urls import path

from . import views

urlpatterns = [
    path("", views.HomeView.as_view(), name="home"),
    path("channels/", views.ChannelListView.as_view(), name="channel-list"),
    path("channel/<int:pk>/", views.ChannelDetailView.as_view(), name="channel-detail"),
    path("data/", views.DataView.as_view(), name="data"),
    path("search/", views.MessageSearchView.as_view(), name="message-search"),
]
