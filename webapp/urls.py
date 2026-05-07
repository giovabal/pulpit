from django.urls import path

from . import views

urlpatterns = [
    path("", views.HomeView.as_view(), name="home"),
    path("channels/", views.ChannelListView.as_view(), name="channel-list"),
    path("channels/vacancies/", views.VacanciesView.as_view(), name="channel-vacancies"),
    path("channel/<int:pk>/", views.ChannelDetailView.as_view(), name="channel-detail"),
    path("channel/<int:pk>/vacancy-analysis/", views.VacancyAnalysisView.as_view(), name="channel-vacancy-analysis"),
    path(
        "channel/<int:channel_pk>/message/<int:telegram_id>/replies/",
        views.MessageRepliesView.as_view(),
        name="message-replies",
    ),
    path("search/", views.MessageSearchView.as_view(), name="message-search"),
]
