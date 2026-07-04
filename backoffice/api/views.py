import datetime

from django.contrib.auth.models import User
from django.db import transaction
from django.db.models import Count, Exists, OuterRef, Prefetch, ProtectedError, Q

from events.models import Event, EventType
from webapp.models import (
    Channel,
    ChannelLabel,
    ChannelSource,
    ChannelVacancy,
    Label,
    LabelGroup,
    ProfilePicture,
    Project,
    SearchTerm,
)

from .serializers import (
    ChannelLabelSerializer,
    ChannelSerializer,
    ChannelSourceSerializer,
    ChannelVacancySerializer,
    EventSerializer,
    EventTypeSerializer,
    LabelGroupSerializer,
    LabelSerializer,
    ProjectSerializer,
    SearchTermSerializer,
    UserSerializer,
)
from .utils import UnaccentLower, normalize_for_search

from rest_framework import generics, mixins, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied, ValidationError
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
        return ChannelVacancy.objects.select_related("channel", "successor").order_by("-closure_date")


class LabelGroupViewSet(viewsets.ModelViewSet):
    serializer_class = LabelGroupSerializer

    def get_queryset(self):
        # Primary group first (it is the "Organization" replacement), then alphabetical.
        return LabelGroup.objects.annotate(label_count=Count("labels", distinct=True)).order_by("-is_primary", "name")


class LabelViewSet(viewsets.ModelViewSet):
    serializer_class = LabelSerializer

    def get_queryset(self):
        qs = (
            Label.objects.select_related("group")
            .annotate(channel_count=Count("channel_labels__channel", distinct=True))
            .order_by("group__name", "name")
        )
        group_id = self.request.query_params.get("group", "").strip()
        if group_id:
            if not group_id.isdigit():
                raise ValidationError({"group": "must be an integer"})
            qs = qs.filter(group_id=int(group_id))
        return qs


class ChannelSourceViewSet(viewsets.ModelViewSet):
    serializer_class = ChannelSourceSerializer

    def get_queryset(self):
        return ChannelSource.objects.annotate(channel_count=Count("channels")).order_by("name")


class ChannelViewSet(
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    mixins.UpdateModelMixin,
    viewsets.GenericViewSet,
):
    serializer_class = ChannelSerializer
    http_method_names = ["get", "patch", "post", "head", "options"]
    filter_backends = [OrderingFilter]
    ordering_fields = ["id", "title", "participants_count", "in_degree", "_created"]
    ordering = ["-id"]

    def get_queryset(self):
        qs = Channel.objects.prefetch_related(
            "channel_labels__label__group",
            "sources",
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

        label_id = self.request.query_params.get("label", "").strip()
        if label_id:
            # Postgres raises InvalidTextRepresentation on a non-integer FK
            # value (500); SQLite silently returns nothing. Reject explicitly
            # so the contract is the same across backends.
            if not label_id.isdigit():
                raise ValidationError({"label": "must be an integer"})
            qs = qs.filter(channel_labels__label_id=int(label_id)).distinct()

        source_id = self.request.query_params.get("source", "").strip()
        if source_id:
            if not source_id.isdigit():
                raise ValidationError({"source": "must be an integer"})
            qs = qs.filter(sources__id=int(source_id)).distinct()

        status_filter = self.request.query_params.get("status", "").strip()
        if status_filter == "unassigned":
            qs = qs.filter(channel_labels__isnull=True)
        elif status_filter == "in_target":
            in_target_label = ChannelLabel.objects.filter(channel=OuterRef("pk"), label__is_in_target=True)
            qs = qs.filter(Exists(in_target_label)).exclude(is_lost=True).exclude(is_private=True)
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
        label_id = request.data.get("label_id")
        add_source_ids = _validate_id_list(request.data.get("add_source_ids", []))
        remove_source_ids = _validate_id_list(request.data.get("remove_source_ids", []))
        if add_source_ids is None or remove_source_ids is None:
            return Response(
                {"error": "'add_source_ids' and 'remove_source_ids' must be lists of integers."},
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

        # Resolve/validate the label before touching the DB so a bad id can never silently
        # wipe a channel's labels. Absent key = leave labels alone; null/"" = intentional
        # unassign (clear every label); a non-existent or non-integer id is a 400.
        assign_label = "label_id" in request.data
        label = None
        if assign_label and label_id not in (None, ""):
            try:
                label_pk = int(label_id)
            except (TypeError, ValueError):
                return Response(
                    {"error": "'label_id' must be an integer or null."},
                    status=status.HTTP_400_BAD_REQUEST,
                )
            label = Label.objects.select_related("group").filter(pk=label_pk).first()
            if label is None:
                return Response(
                    {"error": "'label_id' does not match an existing label."},
                    status=status.HTTP_400_BAD_REQUEST,
                )

        channels = Channel.objects.filter(pk__in=ids)
        # Materialised once: the M2M add/remove below must only see ids that still
        # match a Channel row — a stale selection (channel deleted between page load
        # and submit) would otherwise violate the FK constraint and 500 the whole
        # request, rolling back the attribution changes too.
        valid_ids = list(channels.values_list("pk", flat=True))

        with transaction.atomic():
            if assign_label:
                if label is not None:
                    # Replace each channel's periods *within the label's group* with one period
                    # (whole lifetime when start/end are omitted). Scoping the delete to the group
                    # leaves the channel's labels in other groups intact. Never overlaps.
                    ChannelLabel.objects.filter(channel__in=channels, label__group_id=label.group_id).delete()
                    ChannelLabel.objects.bulk_create(
                        [ChannelLabel(channel=ch, label=label, start=start_date, end=end_date) for ch in channels]
                    )
                else:
                    # Explicit unassign: clear every label on the selected channels.
                    ChannelLabel.objects.filter(channel__in=channels).delete()
            # Pass validated ids to ``add()``/``remove()`` so the M2M operation runs
            # once per source, rather than re-evaluating the ``channels`` queryset for
            # each ``*channels`` unpack (which would hit the DB N extra times).
            if add_source_ids:
                for src in ChannelSource.objects.filter(pk__in=add_source_ids):
                    src.channels.add(*valid_ids)
            if remove_source_ids:
                for src in ChannelSource.objects.filter(pk__in=remove_source_ids):
                    src.channels.remove(*valid_ids)

        return Response({"updated": len(valid_ids)})

    @action(detail=True, methods=["post"], url_path="replace-labels")
    def replace_labels(self, request, pk=None):
        """Atomically save a channel's label periods and (optionally) its editable fields.

        This is the channel editor's single save endpoint. Replacing the label
        periods (delete old, recreate new) AND applying the scalar flags
        (is_lost / is_private / to_inspect) and source memberships all happen
        inside one transaction, so a validation or DB error rolls *everything*
        back. That avoids the split-save failure mode where the flags/sources were
        PATCHed separately and stayed committed while the labels failed (or the
        labelling was left half-written by POSTing each period on its own).

        The channel fields are optional: a request with only ``periods`` behaves
        exactly as before.
        """
        channel = self.get_object()
        periods = request.data.get("periods", [])
        if not isinstance(periods, list):
            return Response({"error": "'periods' must be a list."}, status=status.HTTP_400_BAD_REQUEST)

        # Editable channel fields the editor sends alongside the periods; absent keys are left alone.
        field_data = {
            k: request.data[k] for k in ("source_ids", "is_lost", "is_private", "to_inspect") if k in request.data
        }

        with transaction.atomic():
            if field_data:
                # Reuse ChannelSerializer for validation (source_ids existence, field types) and its
                # update() (which applies sources.set). raise_exception rolls back the whole save.
                ch_serializer = self.get_serializer(channel, data=field_data, partial=True)
                ch_serializer.is_valid(raise_exception=True)
                ch_serializer.save()
            ChannelLabel.objects.filter(channel=channel).delete()
            created = []
            for row in periods:
                row = row if isinstance(row, dict) else {}
                serializer = ChannelLabelSerializer(
                    data={
                        "channel_id": channel.id,
                        "label_id": row.get("label_id"),
                        "start": row.get("start") or None,
                        "end": row.get("end") or None,
                    }
                )
                serializer.is_valid(raise_exception=True)
                created.append(serializer.save())

        return Response({"labels": ChannelLabelSerializer(created, many=True).data})


class ChannelLabelViewSet(viewsets.ModelViewSet):
    serializer_class = ChannelLabelSerializer

    def get_queryset(self):
        qs = ChannelLabel.objects.select_related("label", "label__group", "channel").order_by("channel_id", "start")
        channel_id = self.request.query_params.get("channel", "").strip()
        if channel_id:
            if not channel_id.isdigit():
                # 400 like the other id filters in this module — filter() would raise
                # ValueError at evaluation, which DRF surfaces as a 500.
                raise ValidationError({"channel": "must be an integer"})
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

    def create(self, request, *args, **kwargs):
        # Standard create, but add a `created` flag to the body so the client can avoid inserting a
        # duplicate row / inflating its count when get_or_create returned a pre-existing term. The
        # status stays 201 (the endpoint is idempotent by design).
        response = super().create(request, *args, **kwargs)
        serializer = getattr(self, "_last_serializer", None)
        created = getattr(getattr(serializer, "instance", None), "_was_created", True)
        response.data["created"] = created
        return response

    def perform_create(self, serializer):
        serializer.save()
        self._last_serializer = serializer


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
            raise PermissionDenied("You cannot delete your own account.")
        instance.delete()


class ProjectView(generics.RetrieveUpdateAPIView):
    """GET/PUT/PATCH the project dossier singleton (title + description/criteria/notes)."""

    serializer_class = ProjectSerializer

    def get_object(self):
        return Project.load()
