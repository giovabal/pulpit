from django.contrib.auth.models import User
from django.db import transaction

from events.models import Event, EventType
from webapp.models import (
    Channel,
    ChannelLabel,
    ChannelSource,
    ChannelVacancy,
    CustomEmojiPack,
    Domain,
    DomainCategory,
    Label,
    LabelGroup,
    LabelParent,
    Message,
    MessageTag,
    MessageTagging,
    Project,
    SearchTerm,
)
from webapp.models.tag_models import (
    ImpliedTagError,
    TagTree,
    message_origin,
    normalize_tag_name,
    plan_tag_path,
    sibling_clash,
    tag_message_counts,
    tag_name_error,
    tag_post,
)
from webapp.templatetags.custom_emoji import emoji_html

from rest_framework import serializers


class LabelGroupSerializer(serializers.ModelSerializer):
    label_count = serializers.IntegerField(read_only=True)

    class Meta:
        model = LabelGroup
        fields = ["id", "name", "color", "description", "is_partition", "is_primary", "is_container", "label_count"]

    def validate(self, attrs):
        # Refuse to switch a group to a partition while it still holds overlapping label
        # periods for some channel — name the conflicts so the operator can resolve them.
        is_partition = attrs.get("is_partition", getattr(self.instance, "is_partition", False))
        if is_partition and self.instance is not None:
            conflicts = self.instance.partition_conflicts()
            if conflicts:
                raise serializers.ValidationError(self.instance.partition_conflict_message(conflicts))
        # Likewise, refuse to unset container status while child assignments still hang
        # off this group's labels (mirrors LabelGroup.clean, which DRF does not call).
        is_container = attrs.get("is_container", getattr(self.instance, "is_container", False))
        if not is_container and self.instance is not None:
            child_count = LabelParent.objects.filter(parent_group_id=self.instance.pk).count()
            if child_count:
                raise serializers.ValidationError(
                    {
                        "is_container": (
                            f"Cannot unset container: {child_count} label(s) are still assigned under "
                            f"“{self.instance.name}” labels. Remove those assignments first."
                        )
                    }
                )
        # And the mirror image: a container's labels are never channel-linked, so a group
        # cannot become one while channel-label periods still point at its labels.
        if is_container and self.instance is not None:
            link_count = ChannelLabel.objects.filter(label__group_id=self.instance.pk).count()
            if link_count:
                raise serializers.ValidationError(
                    {
                        "is_container": (
                            f"Cannot make “{self.instance.name}” a container: {link_count} channel-label "
                            "period(s) still point at its labels. Remove those channel assignments first."
                        )
                    }
                )
        return attrs

    def _enforce_single_primary(self, instance):
        # Exactly one group is the primary: node colour, the
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
    group_is_container = serializers.BooleanField(source="group.is_container", read_only=True)
    channel_count = serializers.IntegerField(read_only=True)

    class Meta:
        model = Label
        fields = [
            "id",
            "group_id",
            "group_name",
            "group_is_partition",
            "group_is_primary",
            "group_is_container",
            "name",
            "color",
            "is_in_target",
            "channel_count",
        ]


class LabelParentSerializer(serializers.ModelSerializer):
    label_id = serializers.PrimaryKeyRelatedField(source="label", queryset=Label.objects.select_related("group"))
    parent_id = serializers.PrimaryKeyRelatedField(source="parent", queryset=Label.objects.select_related("group"))
    parent_group_id = serializers.IntegerField(source="parent.group_id", read_only=True)
    parent_name = serializers.CharField(source="parent.name", read_only=True)
    label_name = serializers.CharField(source="label.name", read_only=True)
    label_color = serializers.CharField(source="label.color", read_only=True)
    label_group_id = serializers.IntegerField(source="label.group_id", read_only=True)
    label_group_name = serializers.CharField(source="label.group.name", read_only=True)

    class Meta:
        model = LabelParent
        fields = [
            "id",
            "label_id",
            "parent_id",
            "parent_group_id",
            "parent_name",
            "label_name",
            "label_color",
            "label_group_id",
            "label_group_name",
        ]

    def validate(self, attrs):
        label = attrs.get("label") or getattr(self.instance, "label", None)
        parent = attrs.get("parent") or getattr(self.instance, "parent", None)
        if parent is not None and not parent.group.is_container:
            raise serializers.ValidationError({"parent_id": "The parent label must belong to a container group."})
        if label is not None and parent is not None and parent.group_id == label.group_id:
            raise serializers.ValidationError({"label_id": "A container label cannot parent a label of its own group."})
        # Moving an assignment must stay inside its container group — a cross-group
        # parent id on update is a client bug (e.g. a drop event that escaped its card).
        if (
            self.instance is not None
            and "parent" in attrs
            and attrs["parent"].group_id != self.instance.parent_group_id
        ):
            raise serializers.ValidationError({"parent_id": "The new parent must belong to the same container group."})
        return attrs

    def create(self, validated_data):
        # Upsert on (label, parent group): dropping a label that is already assigned to
        # another parent in the same container *moves* it, so drag-and-drop stays a
        # single idempotent POST instead of tripping the uniqueness constraint.
        parent = validated_data["parent"]
        obj, _created = LabelParent.objects.update_or_create(
            label=validated_data["label"], parent_group_id=parent.group_id, defaults={"parent": parent}
        )
        return obj


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
        # Container-group labels only contain other labels — never channels (mirrors
        # ChannelLabel.clean, which DRF does not call).
        if label is not None and label.group.is_container:
            raise serializers.ValidationError(
                {
                    "label_id": (
                        "Labels of a container group cannot be assigned to channels — they only contain other labels."
                    )
                }
            )
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
            "environment_depth",
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
            "environment_depth",
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
    # The labels the event concerns (empty = the whole network): written as ids, read back with names.
    label_ids = serializers.PrimaryKeyRelatedField(
        source="labels", queryset=Label.objects.all(), many=True, required=False
    )
    labels = serializers.SerializerMethodField()

    class Meta:
        model = Event
        fields = ["id", "date", "subject", "action_id", "action_name", "action_color", "label_ids", "labels"]

    def get_labels(self, obj: Event) -> list[dict]:
        return [
            {"id": label.pk, "name": label.name, "group": label.group.name, "color": label.color}
            for label in obj.labels.all()
        ]


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


def _tag_tree(context: dict, tag) -> TagTree:
    """The request's tag tree, loaded once per serialisation and again only for a tag it lacks."""
    tree = context.get("tag_tree")
    if tree is None or tag.pk not in tree.by_id:
        tree = context["tag_tree"] = TagTree.load()
    return tree


class MessageTagRefSerializer(serializers.ModelSerializer):
    """A tag as a chip shows it: colour, name and ``path`` (``"Hand gestures › Nazi salute"``)."""

    is_dark = serializers.BooleanField(source="is_color_dark", read_only=True)
    path = serializers.SerializerMethodField()

    class Meta:
        model = MessageTag
        fields = ["id", "name", "path", "parent", "color", "is_dark"]
        read_only_fields = fields

    def get_path(self, obj):
        return getattr(obj, "tree_path", None) or _tag_tree(self.context, obj).path(obj.pk)


class MessageTagSerializer(MessageTagRefSerializer):
    """A tag with its place in the tree and its counts.

    ``parent`` moves the tag (``null`` = top level; a tag can't go under its own
    branch). ``message_count`` counts the stored messages carrying the tag or a
    sub-tag — what ``?tag=<id>`` lists — and ``own_count`` those carrying the tag
    itself. A sub-tag created without a ``color`` takes its parent's.
    """

    parent = serializers.PrimaryKeyRelatedField(queryset=MessageTag.objects.all(), allow_null=True, required=False)
    depth = serializers.SerializerMethodField()
    message_count = serializers.SerializerMethodField()
    own_count = serializers.SerializerMethodField()

    class Meta:
        model = MessageTag
        fields = [
            "id",
            "name",
            "path",
            "parent",
            "depth",
            "color",
            "description",
            "message_count",
            "own_count",
            "is_dark",
        ]
        read_only_fields = ["id", "path", "depth", "message_count", "own_count", "is_dark"]

    def get_depth(self, obj):
        depth = getattr(obj, "depth", None)
        return len(_tag_tree(self.context, obj).ancestor_ids(obj.pk)) if depth is None else depth

    def _counts(self, obj) -> tuple[int, int]:
        if hasattr(obj, "message_count"):
            return obj.own_count, obj.message_count
        counts = self.context.get("tag_counts")
        if counts is None or obj.pk not in counts:
            counts = self.context["tag_counts"] = tag_message_counts(_tag_tree(self.context, obj))
        return counts.get(obj.pk, (0, 0))

    def get_message_count(self, obj):
        return self._counts(obj)[1]

    def get_own_count(self, obj):
        return self._counts(obj)[0]

    def validate_name(self, value):
        name = normalize_tag_name(value)
        error = tag_name_error(name)
        if error:
            raise serializers.ValidationError(error)
        return name

    def validate(self, attrs):
        instance = self.instance
        name = attrs.get("name", instance.name if instance else "")
        parent = attrs["parent"] if "parent" in attrs else (instance.parent if instance else None)
        if instance is not None and parent is not None and parent.pk in TagTree.load().branch([instance.pk]):
            raise serializers.ValidationError({"parent": "A tag can't go under itself or one of its sub-tags."})
        clash = sibling_clash(name, parent, exclude_pk=instance.pk if instance else None)
        if clash:
            raise serializers.ValidationError({"name": clash})
        return attrs

    def create(self, validated_data):
        parent = validated_data.get("parent")
        if parent is not None and "color" not in validated_data:
            validated_data["color"] = parent.color
        return super().create(validated_data)


class MessageTaggingSerializer(serializers.ModelSerializer):
    """A tag on a post — the original and every share of it.

    Create with ``message`` (the original or any share) plus either ``tag_id`` or
    ``tag_name``. ``tag_name`` is a name or a path (``"Hand gestures/Kühnen
    salute"``, resolved by ``plan_tag_path``): one naming an existing tag reuses
    it (case-insensitively), and the missing part of any other is created on the
    fly — a top-level tag with the next free palette colour, a sub-tag with its
    parent's. Adding a sub-tag of a tag the post carries *refines* that tagging
    (``replaced`` names the tags it replaced); adding a tag the post carries, or
    one implied by a sub-tag it carries, is refused. Only ``note`` changes on
    update; the note belongs to the post, so every message carrying the tag shows
    it. ``member_count`` is the number of stored messages carrying the tagging.
    """

    message = serializers.PrimaryKeyRelatedField(
        queryset=Message.objects.select_related("channel", "forwarded_from"), required=False
    )
    tag = MessageTagRefSerializer(read_only=True)
    tag_id = serializers.PrimaryKeyRelatedField(
        source="tag", queryset=MessageTag.objects.all(), write_only=True, required=False
    )
    tag_name = serializers.CharField(write_only=True, required=False, max_length=255)
    tagged_by = serializers.CharField(source="tagged_by.username", read_only=True, default="")
    tagged_at = serializers.DateTimeField(read_only=True)
    member_count = serializers.SerializerMethodField()
    replaced = serializers.SerializerMethodField()

    class Meta:
        model = MessageTagging
        fields = [
            "id",
            "message",
            "tag",
            "tag_id",
            "tag_name",
            "note",
            "tagged_by",
            "tagged_at",
            "member_count",
            "replaced",
        ]
        # The one-tagging-per-post rule is checked in validate(): DRF's generated
        # UniqueTogetherValidator would demand the origin fields from the client.
        validators = []

    def get_member_count(self, obj):
        count = getattr(obj, "member_count", None)
        return obj.members.count() if count is None else count

    def get_replaced(self, obj):
        replaced = getattr(obj, "replaced", None) or []
        return [_tag_tree(self.context, tag).path(tag.pk) for tag in replaced]

    def validate(self, attrs):
        if self.instance is not None:
            return {"note": attrs.get("note", self.instance.note)}
        if "message" not in attrs:
            raise serializers.ValidationError({"message": "This field is required."})
        raw = attrs.pop("tag_name", "")
        tree = TagTree.load()
        if "tag" not in attrs:
            if not normalize_tag_name(raw):
                raise serializers.ValidationError({"tag_name": "Give a tag_id or a tag_name."})
            try:
                plan = plan_tag_path(raw, tree)
            except ValueError as e:
                raise serializers.ValidationError({"tag_name": str(e)}) from e
            if plan.tag is None:
                attrs["tag_plan"] = plan
                return attrs
            attrs["tag"] = plan.tag
        tag = attrs["tag"]
        channel_tid, post_tid = message_origin(attrs["message"])
        on_post = MessageTagging.objects.filter(origin_channel_tid=channel_tid, origin_post_tid=post_tid)
        for tag_id in on_post.values_list("tag_id", flat=True):
            if tag_id == tag.pk:
                raise serializers.ValidationError(
                    {
                        "tag": f"This post already carries “{tree.path(tag.pk)}” — on this message, its original or a share."
                    }
                )
            if tree.is_ancestor(tag.pk, tag_id):
                raise serializers.ValidationError(
                    {"tag": f"This post already carries “{tree.path(tag_id)}”, which implies “{tree.path(tag.pk)}”."}
                )
        return attrs

    def create(self, validated_data):
        user = self.context["request"].user
        with transaction.atomic():
            tag = validated_data.get("tag") or validated_data["tag_plan"].realise()
            try:
                return tag_post(
                    validated_data["message"],
                    tag,
                    note=validated_data.get("note", ""),
                    tagged_by=user if user.is_authenticated else None,
                )
            except ImpliedTagError as e:  # a sub-tag added since validate() looked
                raise serializers.ValidationError({"tag": [str(e)]}) from e

    def update(self, instance, validated_data):
        instance.note = validated_data["note"]
        instance.save(update_fields=["note", "_updated"])
        return instance


class CustomEmojiPackSerializer(serializers.ModelSerializer):
    """Manage → Emoji: the crawler's packs, of which the analyst sets ``is_in_target`` and ``note``.

    ``uses`` / ``channels`` / ``emoji_used`` count every stored post (the queryset annotates them);
    ``preview_html`` draws the pack's most used emoji, read from the ``previews`` context the
    viewset builds for the page.
    """

    uses = serializers.IntegerField(read_only=True)
    channels = serializers.IntegerField(read_only=True)
    emoji_used = serializers.IntegerField(read_only=True)
    display_title = serializers.CharField(read_only=True)
    telegram_url = serializers.CharField(read_only=True)
    preview_html = serializers.SerializerMethodField()
    group_channels = serializers.SerializerMethodField()

    class Meta:
        model = CustomEmojiPack
        fields = [
            "id",
            "telegram_id",
            "title",
            "short_name",
            "display_title",
            "telegram_url",
            "emoji_count",
            "is_unavailable",
            "is_in_target",
            "note",
            "uses",
            "channels",
            "emoji_used",
            "preview_html",
            "group_channels",
        ]
        read_only_fields = ["telegram_id", "title", "short_name", "emoji_count", "is_unavailable"]

    def update(self, instance: CustomEmojiPack, validated_data: dict) -> CustomEmojiPack:
        # Save only the fields sent: the page PATCHes the toggle and the note separately, often a
        # moment apart (the note's change event fires as the checkbox is clicked), and a whole-row
        # save from the second request would write back the first one's field as it was before.
        for field, value in validated_data.items():
            setattr(instance, field, value)
        instance.save(update_fields=[*validated_data, "_updated"])
        return instance

    def get_group_channels(self, obj: CustomEmojiPack) -> list[dict]:
        """The groups that set this pack as their own emoji pack (``Channel.emoji_pack``)."""
        return [{"id": c.pk, "title": c.title, "url": c.get_absolute_url()} for c in obj.group_channels.all()]

    def get_preview_html(self, obj: CustomEmojiPack) -> str:
        return "".join(str(emoji_html(e, play="hover")) for e in self.context.get("previews", {}).get(obj.pk, [])[:3])


class DomainCategorySerializer(serializers.ModelSerializer):
    """Manage → Domains: an analyst-defined kind of site; ``domain_count`` is annotated by the viewset."""

    domain_count = serializers.IntegerField(read_only=True)

    class Meta:
        model = DomainCategory
        fields = ["id", "name", "color", "role", "description", "domain_count"]


class DomainSerializer(serializers.ModelSerializer):
    """Manage → Domains: a linked site with the counts of the last ``index_domains`` run; only ``category``
    and ``note`` are editable, each saved on its own (see :meth:`update`)."""

    class Meta:
        model = Domain
        fields = ["id", "name", "category", "note", "posts", "channels", "first_seen", "last_seen"]
        read_only_fields = ["name", "posts", "channels", "first_seen", "last_seen"]

    def update(self, instance: Domain, validated_data: dict) -> Domain:
        # The page PATCHes the category and the note separately, possibly a moment apart.
        for field, value in validated_data.items():
            setattr(instance, field, value)
        instance.save(update_fields=[*validated_data, "_updated"])
        return instance
