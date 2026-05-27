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
    ChannelAttributionViewSet,
    ChannelGroupViewSet,
    ChannelVacancyViewSet,
    ChannelViewSet,
    EventTypeViewSet,
    EventViewSet,
    OrganizationViewSet,
    SearchTermViewSet,
    UserViewSet,
)

from rest_framework.routers import DefaultRouter

router = DefaultRouter(trailing_slash=True)
router.register("channels", ChannelViewSet, basename="api-channels")
router.register("channel-attributions", ChannelAttributionViewSet, basename="api-channel-attributions")
router.register("organizations", OrganizationViewSet, basename="api-organizations")
router.register("groups", ChannelGroupViewSet, basename="api-groups")
router.register("search-terms", SearchTermViewSet, basename="api-search-terms")
router.register("event-types", EventTypeViewSet, basename="api-event-types")
router.register("events", EventViewSet, basename="api-events")
router.register("users", UserViewSet, basename="api-users")
router.register("vacancies", ChannelVacancyViewSet, basename="api-vacancies")

urlpatterns = [
    *router.urls,
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
