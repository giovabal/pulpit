from django.urls import path

from .maintenance import (
    check_updates,
    maintenance_info,
    maintenance_optimize,
    orphan_media_preview,
    orphan_media_run,
    purge_preview,
    purge_run,
)
from .views import (
    ChannelLabelViewSet,
    ChannelSourceViewSet,
    ChannelVacancyViewSet,
    ChannelViewSet,
    EventTypeViewSet,
    EventViewSet,
    LabelGroupViewSet,
    LabelViewSet,
    ProjectView,
    SearchTermViewSet,
    UserViewSet,
)

from rest_framework.routers import DefaultRouter

router = DefaultRouter(trailing_slash=True)
router.register("channels", ChannelViewSet, basename="api-channels")
router.register("channel-labels", ChannelLabelViewSet, basename="api-channel-labels")
router.register("label-groups", LabelGroupViewSet, basename="api-label-groups")
router.register("labels", LabelViewSet, basename="api-labels")
router.register("sources", ChannelSourceViewSet, basename="api-sources")
router.register("search-terms", SearchTermViewSet, basename="api-search-terms")
router.register("event-types", EventTypeViewSet, basename="api-event-types")
router.register("events", EventViewSet, basename="api-events")
router.register("users", UserViewSet, basename="api-users")
router.register("vacancies", ChannelVacancyViewSet, basename="api-vacancies")

urlpatterns = [
    *router.urls,
    path("project/", ProjectView.as_view(), name="api-project"),
    path("maintenance/", maintenance_info, name="api-maintenance-info"),
    path("maintenance/check-updates/", check_updates, name="api-maintenance-check-updates"),
    path("maintenance/optimize/", maintenance_optimize, name="api-maintenance-optimize"),
    path("maintenance/purge-preview/", purge_preview, name="api-maintenance-purge-preview"),
    path("maintenance/purge/", purge_run, name="api-maintenance-purge"),
    path(
        "maintenance/orphan-media-preview/",
        orphan_media_preview,
        name="api-maintenance-orphan-media-preview",
    ),
    path(
        "maintenance/orphan-media/",
        orphan_media_run,
        name="api-maintenance-orphan-media",
    ),
]
