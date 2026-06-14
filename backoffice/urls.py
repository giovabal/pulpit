from django.urls import include, path
from django.views.generic import RedirectView

from .views import (
    ChannelsView,
    ChannelUpdateView,
    EventsView,
    GroupsView,
    LabelsView,
    MaintenanceView,
    ProjectView,
    SearchTermsView,
    UsersView,
    VacanciesManageView,
)

app_name = "backoffice"

urlpatterns = [
    path("", RedirectView.as_view(pattern_name="backoffice:channels", permanent=False)),
    path("channels/", ChannelsView.as_view(), name="channels"),
    path("channels/<int:pk>/", ChannelUpdateView.as_view(), name="channel-update"),
    path("labels/", LabelsView.as_view(), name="labels"),
    path("groups/", GroupsView.as_view(), name="groups"),
    path("search-terms/", SearchTermsView.as_view(), name="search-terms"),
    path("events/", EventsView.as_view(), name="events"),
    path("users/", UsersView.as_view(), name="users"),
    path("vacancies/", VacanciesManageView.as_view(), name="vacancies"),
    path("project/", ProjectView.as_view(), name="project"),
    path("maintenance/", MaintenanceView.as_view(), name="maintenance"),
    path("api/", include("backoffice.api.urls")),
]
