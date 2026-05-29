import datetime

from django.contrib.auth.models import User
from django.db import transaction
from django.db.models import Count, Exists, OuterRef, Prefetch, ProtectedError, Q

from events.models import Event, EventType
from webapp.models import (
    Channel,
    ChannelAttribution,
    ChannelGroup,
    ChannelVacancy,
    Organization,
    ProfilePicture,
    SearchTerm,
)

from .serializers import (
    ChannelAttributionSerializer,
    ChannelGroupSerializer,
    ChannelSerializer,
    ChannelVacancySerializer,
    EventSerializer,
    EventTypeSerializer,
    OrganizationSerializer,
    SearchTermSerializer,
    UserSerializer,
)
from .utils import UnaccentLower, normalize_for_search

from rest_framework import mixins, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError
from rest_framework.filters import OrderingFilter
from rest_framework.response import Response


def _validate_id_list(raw) -> list[int] | None:
    """Coerce request data into a clean list[int], or None on malformed input.

    Reject non-list payloads (a JSON string body like ``{"ids": "abc"}`` would
    otherwise be iterated character-by-character by ``filter(pk__in=…)``, which
    then raises a confusing 500). Bools are rejected explicitly because they're
    an ``int`` subclass in Python but never valid as a primary key.
    """
    if not isinstance(raw, list):
        return None
    out: list[int] = []
    for item in raw:
        if isinstance(item, bool):
            return None
        try:
            out.append(int(item))
        except (TypeError, ValueError):
            return None
    return out


class ChannelVacancyViewSet(viewsets.ModelViewSet):
    serializer_class = ChannelVacancySerializer

    def get_queryset(self):
        return ChannelVacancy.objects.select_related("channel").order_by("-closure_date")


class OrganizationViewSet(viewsets.ModelViewSet):
    serializer_class = OrganizationSerializer

    def get_queryset(self):
        return Organization.objects.annotate(channel_count=Count("attributions__channel", distinct=True)).order_by(
            "name"
        )


class ChannelGroupViewSet(viewsets.ModelViewSet):
    serializer_class = ChannelGroupSerializer

    def get_queryset(self):
        return ChannelGroup.objects.annotate(channel_count=Count("channels")).order_by("name")


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
        qs = Channel.objects.prefetch_related(
            "attributions__organization",
            "groups",
            Prefetch(
                "profilepicture_set",
                queryset=ProfilePicture.objects.order_by("-date")[:1],
                to_attr="_prefetched_profile_pics",
            ),
        )

        search = self.request.query_params.get("search", "").strip()
        if search:
            norm = normalize_for_search(search)
            qs = qs.annotate(
                _title_norm=UnaccentLower("title"),
                _username_norm=UnaccentLower("username"),
            ).filter(Q(_title_norm__contains=norm) | Q(_username_norm__contains=norm))

        org_id = self.request.query_params.get("organization", "").strip()
        if org_id:
            # Postgres raises InvalidTextRepresentation on a non-integer FK
            # value (500); SQLite silently returns nothing. Reject explicitly
            # so the contract is the same across backends.
            if not org_id.isdigit():
                raise ValidationError({"organization": "must be an integer"})
            qs = qs.filter(attributions__organization_id=int(org_id)).distinct()

        group_id = self.request.query_params.get("group", "").strip()
        if group_id:
            if not group_id.isdigit():
                raise ValidationError({"group": "must be an integer"})
            qs = qs.filter(groups__id=int(group_id)).distinct()

        status_filter = self.request.query_params.get("status", "").strip()
        if status_filter == "unassigned":
            qs = qs.filter(attributions__isnull=True)
        elif status_filter == "in_target":
            in_target_attr = ChannelAttribution.objects.filter(channel=OuterRef("pk"), organization__is_in_target=True)
            qs = qs.filter(Exists(in_target_attr)).exclude(is_lost=True).exclude(is_private=True)
        elif status_filter == "lost":
            qs = qs.filter(is_lost=True)
        elif status_filter == "private":
            qs = qs.filter(is_private=True)
        elif status_filter == "to_inspect":
            qs = qs.filter(to_inspect=True)

        return qs

    @action(detail=True, methods=["get"], url_path="pictures")
    def pictures(self, request, pk=None):
        channel = self.get_object()
        pictures = []
        for pic in channel.profilepicture_set.order_by("-date"):
            if not pic.picture:
                continue
            pictures.append(
                {
                    "url": pic.picture.url,
                    "mime_type": pic.mime_type,
                    "thumbnail_url": (pic.thumbnail.url if pic.thumbnail and pic.thumbnail.name else None),
                }
            )
        return Response({"pictures": pictures})

    @action(detail=False, methods=["post"], url_path="bulk-assign")
    def bulk_assign(self, request):
        ids = _validate_id_list(request.data.get("ids", []))
        if ids is None:
            return Response({"error": "'ids' must be a list of integers."}, status=status.HTTP_400_BAD_REQUEST)
        if not ids:
            return Response({"error": "No channel ids provided."}, status=status.HTTP_400_BAD_REQUEST)
        organization_id = request.data.get("organization_id")
        add_group_ids = _validate_id_list(request.data.get("add_group_ids", []))
        remove_group_ids = _validate_id_list(request.data.get("remove_group_ids", []))
        if add_group_ids is None or remove_group_ids is None:
            return Response(
                {"error": "'add_group_ids' and 'remove_group_ids' must be lists of integers."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        start_raw = request.data.get("start") or None
        end_raw = request.data.get("end") or None
        try:
            start_date = datetime.date.fromisoformat(start_raw) if start_raw else None
            end_date = datetime.date.fromisoformat(end_raw) if end_raw else None
        except (TypeError, ValueError):
            return Response(
                {"error": "'start'/'end' must be ISO dates (YYYY-MM-DD)."}, status=status.HTTP_400_BAD_REQUEST
            )
        if start_date and end_date and start_date > end_date:
            return Response({"error": "'end' must not be before 'start'."}, status=status.HTTP_400_BAD_REQUEST)

        # Resolve/validate the organization before touching the DB so a bad id can never
        # silently wipe attributions. Absent key = leave attributions alone; null/"" =
        # intentional unassign; a non-existent or non-integer id is a 400.
        assign_org = "organization_id" in request.data
        org = None
        if assign_org and organization_id not in (None, ""):
            try:
                org_pk = int(organization_id)
            except (TypeError, ValueError):
                return Response(
                    {"error": "'organization_id' must be an integer or null."},
                    status=status.HTTP_400_BAD_REQUEST,
                )
            org = Organization.objects.filter(pk=org_pk).first()
            if org is None:
                return Response(
                    {"error": "'organization_id' does not match an existing organization."},
                    status=status.HTTP_400_BAD_REQUEST,
                )

        channels = Channel.objects.filter(pk__in=ids)

        with transaction.atomic():
            if assign_org:
                # Replace each selected channel's attribution timeline with one period (whole lifetime
                # when start/end are omitted). org=null leaves the channel unassigned. Never overlaps.
                ChannelAttribution.objects.filter(channel__in=channels).delete()
                if org is not None:
                    ChannelAttribution.objects.bulk_create(
                        [
                            ChannelAttribution(channel=ch, organization=org, start=start_date, end=end_date)
                            for ch in channels
                        ]
                    )
            if add_group_ids:
                for grp in ChannelGroup.objects.filter(pk__in=add_group_ids):
                    grp.channels.add(*channels)
            if remove_group_ids:
                for grp in ChannelGroup.objects.filter(pk__in=remove_group_ids):
                    grp.channels.remove(*channels)

        return Response({"updated": channels.count()})


class ChannelAttributionViewSet(viewsets.ModelViewSet):
    serializer_class = ChannelAttributionSerializer

    def get_queryset(self):
        qs = ChannelAttribution.objects.select_related("organization", "channel").order_by("channel_id", "start")
        channel_id = self.request.query_params.get("channel", "").strip()
        if channel_id:
            qs = qs.filter(channel_id=channel_id)
        return qs


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

    def destroy(self, request, *args, **kwargs):
        # Event.action is on_delete=PROTECT, so deleting an in-use type raises
        # ProtectedError. DRF doesn't translate it, surfacing as a 500; turn it
        # into a clean 409 instead.
        try:
            return super().destroy(request, *args, **kwargs)
        except ProtectedError:
            return Response(
                {"detail": "This event type is still used by one or more events and cannot be deleted."},
                status=status.HTTP_409_CONFLICT,
            )


class EventViewSet(viewsets.ModelViewSet):
    serializer_class = EventSerializer

    def get_queryset(self):
        qs = Event.objects.select_related("action").order_by("-date")
        type_id = self.request.query_params.get("type", "").strip()
        if type_id:
            # Postgres raises InvalidTextRepresentation on a non-integer FK
            # value (500); SQLite silently returns nothing. Reject explicitly
            # so the contract is the same across backends.
            if not type_id.isdigit():
                raise ValidationError({"type": "must be an integer"})
            qs = qs.filter(action_id=int(type_id))
        year = self.request.query_params.get("year", "").strip()
        if year:
            if not year.isdigit():
                raise ValidationError({"year": "must be a 4-digit year"})
            qs = qs.filter(date__year=int(year))
        return qs


class UserViewSet(viewsets.ModelViewSet):
    serializer_class = UserSerializer

    def get_queryset(self):
        # Superusers are managed through the Django admin only — never exposed for
        # listing/edit/deletion via the backoffice API, so a (lesser) staff user
        # cannot demote, deactivate, or delete a superuser account.
        return User.objects.filter(is_superuser=False).order_by("username")

    def perform_destroy(self, instance):
        # Prevent an authenticated user from deleting their own account (lockout).
        user = self.request.user
        if user.is_authenticated and user.pk == instance.pk:
            raise ValidationError({"detail": "You cannot delete your own account."})
        instance.delete()
