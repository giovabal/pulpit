from django.contrib.auth.models import User
from django.db import transaction
from django.db.models import Count, Prefetch, Q

from events.models import Event, EventType
from webapp.models import Channel, ChannelGroup, ChannelVacancy, Organization, ProfilePicture, SearchTerm

from .serializers import (
    ChannelGroupSerializer,
    ChannelSerializer,
    ChannelVacancySerializer,
    EventSerializer,
    EventTypeSerializer,
    OrganizationSerializer,
    SearchTermSerializer,
    UserSerializer,
)
from .utils import UnaccentLower, _normalize

from rest_framework import mixins, status, viewsets
from rest_framework.decorators import action
from rest_framework.filters import OrderingFilter
from rest_framework.response import Response


class ChannelVacancyViewSet(viewsets.ModelViewSet):
    serializer_class = ChannelVacancySerializer

    def get_queryset(self):
        return ChannelVacancy.objects.select_related("channel").order_by("-closure_date")


class OrganizationViewSet(viewsets.ModelViewSet):
    serializer_class = OrganizationSerializer

    def get_queryset(self):
        return Organization.objects.annotate(channel_count=Count("channel")).order_by("name")


class ChannelGroupViewSet(viewsets.ModelViewSet):
    serializer_class = ChannelGroupSerializer

    def get_queryset(self):
        return ChannelGroup.objects.annotate(channel_count=Count("channels")).order_by("name")

    @action(detail=True, methods=["post"], url_path="channels")
    def add_channels(self, request, pk=None):
        group = self.get_object()
        ids = request.data.get("ids", [])
        channels = Channel.objects.filter(pk__in=ids)
        group.channels.add(*channels)
        return Response({"added": channels.count()})

    @action(detail=True, methods=["delete"], url_path="channels")
    def remove_channels(self, request, pk=None):
        group = self.get_object()
        ids = request.data.get("ids", [])
        channels = Channel.objects.filter(pk__in=ids)
        group.channels.remove(*channels)
        return Response({"removed": channels.count()})


class ChannelViewSet(
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    mixins.UpdateModelMixin,
    viewsets.GenericViewSet,
):
    serializer_class = ChannelSerializer
    http_method_names = ["get", "patch", "post", "head", "options"]
    filter_backends = [OrderingFilter]
    ordering_fields = ["id", "title", "participants_count", "in_degree"]
    ordering = ["-id"]

    def get_queryset(self):
        qs = Channel.objects.select_related("organization").prefetch_related(
            "groups",
            Prefetch(
                "profilepicture_set",
                queryset=ProfilePicture.objects.order_by("-date")[:1],
                to_attr="_prefetched_profile_pics",
            ),
        )

        search = self.request.query_params.get("search", "").strip()
        if search:
            norm = _normalize(search)
            qs = qs.annotate(
                _title_norm=UnaccentLower("title"),
                _username_norm=UnaccentLower("username"),
            ).filter(Q(_title_norm__contains=norm) | Q(_username_norm__contains=norm))

        org_id = self.request.query_params.get("organization", "").strip()
        if org_id:
            qs = qs.filter(organization_id=org_id)

        group_id = self.request.query_params.get("group", "").strip()
        if group_id:
            qs = qs.filter(groups__id=group_id).distinct()

        status_filter = self.request.query_params.get("status", "").strip()
        if status_filter == "unassigned":
            qs = qs.filter(organization__isnull=True)
        elif status_filter == "interesting":
            qs = qs.filter(organization__is_interesting=True).exclude(is_lost=True).exclude(is_private=True)
        elif status_filter == "lost":
            qs = qs.filter(is_lost=True)
        elif status_filter == "private":
            qs = qs.filter(is_private=True)

        return qs

    @action(detail=True, methods=["get"], url_path="pictures")
    def pictures(self, request, pk=None):
        channel = self.get_object()
        urls = [pic.picture.url for pic in channel.profilepicture_set.order_by("-date") if pic.picture]
        return Response({"pictures": urls})

    @action(detail=False, methods=["post"], url_path="bulk-assign")
    def bulk_assign(self, request):
        ids = request.data.get("ids", [])
        organization_id = request.data.get("organization_id")
        add_group_ids = request.data.get("add_group_ids", [])
        remove_group_ids = request.data.get("remove_group_ids", [])

        if not ids:
            return Response({"error": "No channel ids provided."}, status=status.HTTP_400_BAD_REQUEST)

        channels = Channel.objects.filter(pk__in=ids)

        with transaction.atomic():
            if "organization_id" in request.data:
                org = Organization.objects.filter(pk=organization_id).first() if organization_id else None
                channels.update(organization=org)
            if add_group_ids:
                add_groups = ChannelGroup.objects.filter(pk__in=add_group_ids)
                for ch in channels:
                    ch.groups.add(*add_groups)
            if remove_group_ids:
                remove_groups = ChannelGroup.objects.filter(pk__in=remove_group_ids)
                for ch in channels:
                    ch.groups.remove(*remove_groups)

        return Response({"updated": channels.count()})


class SearchTermViewSet(
    mixins.ListModelMixin,
    mixins.CreateModelMixin,
    mixins.DestroyModelMixin,
    viewsets.GenericViewSet,
):
    serializer_class = SearchTermSerializer

    def get_queryset(self):
        return SearchTerm.objects.order_by("word")


class EventTypeViewSet(viewsets.ModelViewSet):
    serializer_class = EventTypeSerializer

    def get_queryset(self):
        return EventType.objects.annotate(event_count=Count("events")).order_by("name")


class EventViewSet(viewsets.ModelViewSet):
    serializer_class = EventSerializer

    def get_queryset(self):
        qs = Event.objects.select_related("action").order_by("-date")
        type_id = self.request.query_params.get("type", "").strip()
        if type_id:
            qs = qs.filter(action_id=type_id)
        year = self.request.query_params.get("year", "").strip()
        if year:
            qs = qs.filter(date__year=year)
        return qs


class UserViewSet(viewsets.ModelViewSet):
    serializer_class = UserSerializer

    def get_queryset(self):
        return User.objects.order_by("username")
