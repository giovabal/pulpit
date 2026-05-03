from django.contrib.auth.models import User

from events.models import Event, EventType
from webapp.models import Channel, ChannelGroup, ChannelVacancy, Organization, SearchTerm

from rest_framework import serializers


class OrganizationSerializer(serializers.ModelSerializer):
    channel_count = serializers.IntegerField(read_only=True)

    class Meta:
        model = Organization
        fields = ["id", "name", "color", "is_interesting", "channel_count"]


class ChannelVacancySerializer(serializers.ModelSerializer):
    channel_id = serializers.PrimaryKeyRelatedField(source="channel", queryset=Channel.objects.all())
    channel_title = serializers.CharField(source="channel.title", read_only=True)

    class Meta:
        model = ChannelVacancy
        fields = ["id", "channel_id", "channel_title", "closure_date", "note"]


class ChannelGroupSerializer(serializers.ModelSerializer):
    channel_count = serializers.IntegerField(read_only=True)

    class Meta:
        model = ChannelGroup
        fields = ["id", "name", "description", "note", "channel_count"]


class ChannelSerializer(serializers.ModelSerializer):
    organization_id = serializers.PrimaryKeyRelatedField(
        source="organization",
        queryset=Organization.objects.all(),
        allow_null=True,
        required=False,
    )
    organization_name = serializers.CharField(source="organization.name", read_only=True, default=None)
    organization_color = serializers.CharField(source="organization.color", read_only=True, default=None)
    group_ids = serializers.PrimaryKeyRelatedField(
        many=True,
        source="groups",
        queryset=ChannelGroup.objects.all(),
        required=False,
    )
    channel_type = serializers.CharField(read_only=True)
    profile_picture_url = serializers.SerializerMethodField()

    def get_profile_picture_url(self, obj):
        pic = obj.profile_picture
        if pic and pic.picture:
            return pic.picture.url
        return None

    class Meta:
        model = Channel
        fields = [
            "id",
            "title",
            "username",
            "channel_type",
            "profile_picture_url",
            "organization_id",
            "organization_name",
            "organization_color",
            "group_ids",
            "participants_count",
            "in_degree",
            "out_degree",
            "is_lost",
            "is_private",
            "date",
        ]
        read_only_fields = [
            "id",
            "title",
            "username",
            "channel_type",
            "profile_picture_url",
            "participants_count",
            "in_degree",
            "out_degree",
            "date",
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
        read_only_fields = ["id", "username", "date_joined", "is_staff", "is_active"]

    def create(self, validated_data):
        password = validated_data.pop("password", None)
        if not password:
            raise serializers.ValidationError({"password": "Password is required when creating a user."})
        email = validated_data.get("email", "").strip()
        if not email:
            raise serializers.ValidationError({"email": "Email is required."})
        validated_data["username"] = email
        user = User(**validated_data)
        user.set_password(password)
        user.save()
        return user

    def update(self, instance, validated_data):
        password = validated_data.pop("password", None)
        if "email" in validated_data:
            validated_data["username"] = validated_data["email"]
        for attr, value in validated_data.items():
            setattr(instance, attr, value)
        if password:
            instance.set_password(password)
        instance.save()
        return instance
