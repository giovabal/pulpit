from django.contrib.auth.models import User

from events.models import Event, EventType
from webapp.models import (
    Channel,
    ChannelAttribution,
    ChannelGroup,
    ChannelVacancy,
    Organization,
    Project,
    SearchTerm,
)

from rest_framework import serializers


class OrganizationSerializer(serializers.ModelSerializer):
    channel_count = serializers.IntegerField(read_only=True)

    class Meta:
        model = Organization
        fields = ["id", "name", "color", "is_in_target", "channel_count"]


class ProjectSerializer(serializers.ModelSerializer):
    class Meta:
        model = Project
        fields = ["title", "description", "criteria", "notes"]


class ChannelVacancySerializer(serializers.ModelSerializer):
    channel_id = serializers.PrimaryKeyRelatedField(source="channel", queryset=Channel.objects.all())
    channel_title = serializers.CharField(source="channel.title", read_only=True)

    class Meta:
        model = ChannelVacancy
        fields = ["id", "channel_id", "channel_title", "closure_date", "note"]


class ChannelGroupSerializer(serializers.ModelSerializer):
    channel_count = serializers.IntegerField(read_only=True)
    key = serializers.SlugField(required=False, allow_blank=True, max_length=100)

    class Meta:
        model = ChannelGroup
        fields = ["id", "name", "key", "description", "note", "channel_count"]


class ChannelAttributionSerializer(serializers.ModelSerializer):
    channel_id = serializers.PrimaryKeyRelatedField(source="channel", queryset=Channel.objects.all())
    organization_id = serializers.PrimaryKeyRelatedField(source="organization", queryset=Organization.objects.all())
    organization_name = serializers.CharField(source="organization.name", read_only=True)
    organization_color = serializers.CharField(source="organization.color", read_only=True)

    class Meta:
        model = ChannelAttribution
        fields = ["id", "channel_id", "organization_id", "organization_name", "organization_color", "start", "end"]

    def validate(self, attrs):
        channel = attrs.get("channel") or getattr(self.instance, "channel", None)
        start = attrs.get("start", getattr(self.instance, "start", None))
        end = attrs.get("end", getattr(self.instance, "end", None))
        if start and end and start > end:
            raise serializers.ValidationError({"end": "End date must not be before start date."})
        if channel is not None:
            siblings = ChannelAttribution.objects.filter(channel=channel)
            if self.instance is not None:
                siblings = siblings.exclude(pk=self.instance.pk)
            for other in siblings.select_related("organization"):
                if ChannelAttribution._overlaps(start, end, other.start, other.end):
                    raise serializers.ValidationError(
                        "Attribution periods for a channel must not overlap "
                        f"(conflicts with {other.organization} [{other.start or '…'}, {other.end or '…'}])."
                    )
        return attrs


class ChannelSerializer(serializers.ModelSerializer):
    current_organization_id = serializers.SerializerMethodField()
    current_organization_name = serializers.SerializerMethodField()
    current_organization_color = serializers.SerializerMethodField()
    attributions = ChannelAttributionSerializer(many=True, read_only=True)
    group_ids = serializers.PrimaryKeyRelatedField(
        many=True,
        source="groups",
        queryset=ChannelGroup.objects.all(),
        required=False,
    )
    channel_type = serializers.CharField(read_only=True)
    profile_picture_url = serializers.SerializerMethodField()
    profile_picture_mime_type = serializers.SerializerMethodField()
    profile_picture_thumbnail_url = serializers.SerializerMethodField()
    detail_url = serializers.SerializerMethodField()

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

    def get_current_organization_id(self, obj):
        org = obj.current_organization
        return org.id if org else None

    def get_current_organization_name(self, obj):
        org = obj.current_organization
        return org.name if org else None

    def get_current_organization_color(self, obj):
        org = obj.current_organization
        return org.color if org else None

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
            "current_organization_id",
            "current_organization_name",
            "current_organization_color",
            "attributions",
            "group_ids",
            "participants_count",
            "in_degree",
            "out_degree",
            "is_lost",
            "is_private",
            "to_inspect",
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
        groups = validated_data.pop("groups", None)
        instance = super().update(instance, validated_data)
        if groups is not None:
            instance.groups.set(groups)
        return instance


class SearchTermSerializer(serializers.ModelSerializer):
    class Meta:
        model = SearchTerm
        fields = ["id", "word", "last_check"]
        read_only_fields = ["last_check"]

    def create(self, validated_data):
        # Reuse the model's lowercasing/dedup via get_or_create.
        obj, _ = SearchTerm.objects.get_or_create(word=validated_data["word"].strip().lower())
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
