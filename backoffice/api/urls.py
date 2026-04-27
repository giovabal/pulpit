from .views import (
    ChannelGroupViewSet,
    ChannelViewSet,
    EventTypeViewSet,
    EventViewSet,
    OrganizationViewSet,
    SearchTermViewSet,
)

from rest_framework.routers import DefaultRouter

router = DefaultRouter(trailing_slash=True)
router.register("channels", ChannelViewSet, basename="api-channels")
router.register("organizations", OrganizationViewSet, basename="api-organizations")
router.register("groups", ChannelGroupViewSet, basename="api-groups")
router.register("search-terms", SearchTermViewSet, basename="api-search-terms")
router.register("event-types", EventTypeViewSet, basename="api-event-types")
router.register("events", EventViewSet, basename="api-events")

urlpatterns = router.urls
