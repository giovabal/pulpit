from django.urls import path

from . import views

urlpatterns = [
    path("", views.HomeView.as_view(), name="home"),
    path("channel/<int:pk>/", views.ChannelDetailView.as_view(), name="channel-detail"),
]
