from django.contrib.auth.models import User

from events.models import Event, EventType
from webapp.models import (
    Channel,
    ChannelLabel,
    ChannelSource,
    ChannelVacancy,
    Label,
    LabelGroup,
    Project,
    SearchTerm,
)

from rest_framework import serializers


class LabelGroupSerializer(serializers.ModelSerializer):
    label_count = serializers.IntegerField(read_only=True)

    class Meta:
        model = LabelGroup
        fields = ["id", "name", "color", "description", "is_partition", "is_primary", "label_count"]

    def validate(self, attrs):
        # Refuse to switch a group to a partition while it still holds overlapping label
        # periods for some channel — name the conflicts so the operator can resolve them.
        is_partition = attrs.get("is_partition", getattr(self.instance, "is_partition", False))
        if is_partition and self.instance is not None:
            conflicts = self.instance.partition_conflicts()
            if conflicts:
                raise serializers.ValidationError(self.instance.partition_conflict_message(conflicts))
        return attrs

    def _enforce_single_primary(self, instance):
        # Exactly one group is the primary ("Organization" replacement): node colour, the
        # Label export column, vacancy actor identity, and the default MODULEROLE
        # basis all read ``filter(is_primary=True).first()``. Demote any other primary so
        # promoting a group here can't leave two.
        if instance.is_primary:
            LabelGroup.objects.exclude(pk=instance.pk).filter(is_primary=True).update(is_primary=False)

    def create(self, validated_data):
        instance = super().create(validated_data)
        self._enforce_single_primary(instance)
        return instance

    def update(self, instance, validated_data):
        instance = super().update(instance, validated_data)
        self._enforce_single_primary(instance)
        return instance


class LabelSerializer(serializers.ModelSerializer):
    group_id = serializers.PrimaryKeyRelatedField(source="group", queryset=LabelGroup.objects.all())
    group_name = serializers.CharField(source="group.name", read_only=True)
    group_is_partition = serializers.BooleanField(source="group.is_partition", read_only=True)
    group_is_primary = serializers.BooleanField(source="group.is_primary", read_only=True)
    channel_count = serializers.IntegerField(read_only=True)

    class Meta:
        model = Label
        fields = [
            "id",
            "group_id",
            "group_name",
            "group_is_partition",
            "group_is_primary",
            "name",
            "color",
            "is_in_target",
            "channel_count",
        ]


class ProjectSerializer(serializers.ModelSerializer):
    class Meta:
        model = Project
        fields = ["title", "description", "criteria", "notes"]


class ChannelVacancySerializer(serializers.ModelSerializer):
    channel_id = serializers.PrimaryKeyRelatedField(source="channel", queryset=Channel.objects.all())
    channel_title = serializers.CharField(source="channel.title", read_only=True)
    successor_id = serializers.PrimaryKeyRelatedField(
        source="successor", queryset=Channel.objects.all(), allow_null=True, required=False
    )
    successor_title = serializers.SerializerMethodField()

    class Meta:
        model = ChannelVacancy
        fields = ["id", "channel_id", "channel_title", "closure_date", "note", "successor_id", "successor_title"]

    def get_successor_title(self, obj):
        return obj.successor.title if obj.successor_id else None

    def validate(self, attrs):
        channel = attrs.get("channel", getattr(self.instance, "channel", None))
        if "successor" in attrs:
            successor = attrs["successor"]
        else:
            successor = getattr(self.instance, "successor", None)
        if channel and successor and channel.pk == successor.pk:
            raise serializers.ValidationError({"successor_id": "A vacancy channel cannot be its own successor."})
        return attrs


class ChannelSourceSerializer(serializers.ModelSerializer):
    channel_count = serializers.IntegerField(read_only=True)
    key = serializers.SlugField(required=False, allow_blank=True, max_length=100)

    class Meta:
        model = ChannelSource
        fields = ["id", "name", "key", "description", "note", "channel_count"]


class ChannelLabelSerializer(serializers.ModelSerializer):
    channel_id = serializers.PrimaryKeyRelatedField(source="channel", queryset=Channel.objects.all())
    label_id = serializers.PrimaryKeyRelatedField(source="label", queryset=Label.objects.all())
    label_name = serializers.CharField(source="label.name", read_only=True)
    label_color = serializers.CharField(source="label.color", read_only=True)
    group_id = serializers.IntegerField(source="label.group_id", read_only=True)
    group_name = serializers.CharField(source="label.group.name", read_only=True)
    group_is_partition = serializers.BooleanField(source="label.group.is_partition", read_only=True)

    class Meta:
        model = ChannelLabel
        fields = [
            "id",
            "channel_id",
            "label_id",
            "label_name",
            "label_color",
            "group_id",
            "group_name",
            "group_is_partition",
            "start",
            "end",
        ]

    def validate(self, attrs):
        channel = attrs.get("channel") or getattr(self.instance, "channel", None)
        label = attrs.get("label") or getattr(self.instance, "label", None)
        start = attrs.get("start", getattr(self.instance, "start", None))
        end = attrs.get("end", getattr(self.instance, "end", None))
        if start and end and start > end:
            raise serializers.ValidationError({"end": "End date must not be before start date."})
        # Overlap is constrained only within a partition group — there a channel holds at
        # most one of the group's labels at a time. Non-partition groups allow concurrent
        # (overlapping) memberships, so they're never rejected here.
        if channel is not None and label is not None and label.group.is_partition:
            siblings = ChannelLabel.objects.filter(channel=channel, label__group_id=label.group_id).select_related(
                "label", "label__group"
            )
            if self.instance is not None:
                siblings = siblings.exclude(pk=self.instance.pk)
            for other in siblings:
                if ChannelLabel._overlaps(start, end, other.start, other.end):
                    raise serializers.ValidationError(
                        "Label periods within a partition group must not overlap "
                        f"(conflicts with {other.label} [{other.start or '…'}, {other.end or '…'}])."
                    )
        return attrs


class ChannelSerializer(serializers.ModelSerializer):
    current_labels = serializers.SerializerMethodField()
    labels = ChannelLabelSerializer(many=True, read_only=True, source="channel_labels")
    source_ids = serializers.PrimaryKeyRelatedField(
        many=True,
        source="sources",
        queryset=ChannelSource.objects.all(),
        required=False,
    )
    channel_type = serializers.CharField(read_only=True)
    profile_picture_url = serializers.SerializerMethodField()
    profile_picture_mime_type = serializers.SerializerMethodField()
    profile_picture_thumbnail_url = serializers.SerializerMethodField()
    detail_url = serializers.SerializerMethodField()
    first_seen = serializers.DateTimeField(source="_created", read_only=True)

    def get_profile_picture_url(self, obj):
        pic = obj.profile_picture
        if pic and pic.picture:
            return pic.picture.url
        return None

    def get_profile_picture_mime_type(self, obj):
        pic = obj.profile_picture
        return pic.mime_type if pic else ""

    def get_profile_picture_thumbnail_url(self, obj):
        pic = obj.profile_picture
        if pic and pic.thumbnail and pic.thumbnail.name:
            return pic.thumbnail.url
        return None

    def get_detail_url(self, obj):
        return obj.get_absolute_url()

    def get_current_labels(self, obj):
        # The channel's representative label in every group it participates in (active now),
        # for the multi-label "Labels" column. Primary group first (see Channel.current_labels).
        return [
            {
                "id": label.id,
                "name": label.name,
                "color": label.color,
                "group_id": label.group_id,
                "group_name": label.group.name,
                "group_is_primary": label.group.is_primary,
            }
            for label in obj.current_labels
        ]

    class Meta:
        model = Channel
        fields = [
            "id",
            "title",
            "username",
            "channel_type",
            "profile_picture_url",
            "profile_picture_mime_type",
            "profile_picture_thumbnail_url",
            "detail_url",
            "current_labels",
            "labels",
            "source_ids",
            "participants_count",
            "in_degree",
            "out_degree",
            "is_lost",
            "is_private",
            "to_inspect",
            "date",
            "first_seen",
            "restriction_reason",
            "message_ttl",
            "noforwards",
            "forum",
            "join_to_send",
            "join_request",
            "level",
            "extra_usernames",
            "linked_chat_id",
            "available_min_id",
            "slowmode_seconds",
            "admins_count",
            "online_count",
            "requests_pending",
            "theme_emoticon",
        ]
        read_only_fields = [
            "id",
            "title",
            "username",
            "channel_type",
            "profile_picture_url",
            "profile_picture_mime_type",
            "profile_picture_thumbnail_url",
            "participants_count",
            "in_degree",
            "out_degree",
            "date",
            "restriction_reason",
            "message_ttl",
            "noforwards",
            "forum",
            "join_to_send",
            "join_request",
            "level",
            "extra_usernames",
            "linked_chat_id",
            "available_min_id",
            "slowmode_seconds",
            "admins_count",
            "online_count",
            "requests_pending",
            "theme_emoticon",
        ]

    def update(self, instance, validated_data):
        sources = validated_data.pop("sources", None)
        instance = super().update(instance, validated_data)
        if sources is not None:
            instance.sources.set(sources)
        return instance


class SearchTermSerializer(serializers.ModelSerializer):
    class Meta:
        model = SearchTerm
        fields = ["id", "word", "last_check"]
        read_only_fields = ["last_check"]

    def create(self, validated_data):
        # Reuse the model's lowercasing/dedup via get_or_create. Stash whether a new row was
        # actually created so the view can tell the client (which otherwise can't distinguish a
        # fresh term from an existing one returned by get_or_create, and would add a phantom row).
        obj, created = SearchTerm.objects.get_or_create(word=validated_data["word"].strip().lower())
        obj._was_created = created
        return obj


class EventTypeSerializer(serializers.ModelSerializer):
    event_count = serializers.IntegerField(read_only=True)

    class Meta:
        model = EventType
        fields = ["id", "name", "description", "color", "event_count"]


class EventSerializer(serializers.ModelSerializer):
    action_id = serializers.PrimaryKeyRelatedField(source="action", queryset=EventType.objects.all())
    action_name = serializers.CharField(source="action.name", read_only=True)
    action_color = serializers.CharField(source="action.color", read_only=True)

    class Meta:
        model = Event
        fields = ["id", "date", "subject", "action_id", "action_name", "action_color"]


class UserSerializer(serializers.ModelSerializer):
    password = serializers.CharField(write_only=True, required=False, style={"input_type": "password"})

    class Meta:
        model = User
        fields = ["id", "username", "email", "is_staff", "is_active", "date_joined", "password"]
        read_only_fields = ["id", "username", "date_joined"]

    def create(self, validated_data):
        password = validated_data.pop("password", None)
        if not password:
            raise serializers.ValidationError({"password": "Password is required when creating a user."})
        email = validated_data.get("email", "").strip()
        if not email:
            raise serializers.ValidationError({"email": "Email is required."})
        if User.objects.filter(username=email).exists():
            raise serializers.ValidationError({"email": "A user with this email already exists."})
        validated_data["email"] = email
        validated_data["username"] = email
        user = User(**validated_data)
        user.set_password(password)
        user.save()
        return user

    def update(self, instance, validated_data):
        password = validated_data.pop("password", None)
        if "email" in validated_data:
            email = validated_data["email"].strip()
            if not email:
                raise serializers.ValidationError({"email": "Email is required."})
            if User.objects.filter(username=email).exclude(pk=instance.pk).exists():
                raise serializers.ValidationError({"email": "A user with this email already exists."})
            validated_data["email"] = email
            validated_data["username"] = email
        for attr, value in validated_data.items():
            setattr(instance, attr, value)
        if password:
            instance.set_password(password)
        instance.save()
        return instance
