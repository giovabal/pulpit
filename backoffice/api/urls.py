from .views import (
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
router.register("organizations", OrganizationViewSet, basename="api-organizations")
router.register("groups", ChannelGroupViewSet, basename="api-groups")
router.register("search-terms", SearchTermViewSet, basename="api-search-terms")
router.register("event-types", EventTypeViewSet, basename="api-event-types")
router.register("events", EventViewSet, basename="api-events")
router.register("users", UserViewSet, basename="api-users")
router.register("vacancies", ChannelVacancyViewSet, basename="api-vacancies")

urlpatterns = router.urls
