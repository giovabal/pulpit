from django.urls import path

from . import views

urlpatterns = [
    path("", views.HomeView.as_view(), name="home"),
    path("channels/", views.ChannelListView.as_view(), name="channel-list"),
    path("channels/vacancies/", views.VacanciesView.as_view(), name="channel-vacancies"),
    path("channel/<int:pk>/", views.ChannelDetailView.as_view(), name="channel-detail"),
    path("channel/<int:pk>/vacancy-analysis/", views.VacancyAnalysisView.as_view(), name="channel-vacancy-analysis"),
    path("search/", views.MessageSearchView.as_view(), name="message-search"),
]
