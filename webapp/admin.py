from django import forms
from django.contrib import admin
from django.core.exceptions import ValidationError
from django.db.models import Count, Prefetch, QuerySet
from django.http import HttpRequest
from django.utils.html import format_html

from .models import (
    Channel,
    ChannelGroup,
    ChannelLabel,
    Label,
    LabelGroup,
    Message,
    MessagePicture,
    Poll,
    PollAnswer,
    ProfilePicture,
    Project,
    SearchTerm,
)


class ChannelLabelInlineFormSet(forms.BaseInlineFormSet):
    def add_fields(self, form: forms.Form, index: int | None) -> None:
        super().add_fields(form, index)
        # This formset checks overlap on the submitted timeline as a whole (clean()
        # below); flag each instance so ChannelLabel.clean() skips its per-row
        # DB-sibling check, which sees pre-save state and would reject valid
        # combined edits.
        form.instance._overlap_checked_by_formset = True

    def clean(self) -> None:
        super().clean()
        # Overlap is constrained only *within a partition group* — there a channel holds at
        # most one of the group's labels at a time. Collect the submitted periods per
        # partition group and check pairwise; non-partition groups are left unconstrained.
        per_group: dict[int, list[tuple]] = {}
        for form in self.forms:
            if not hasattr(form, "cleaned_data") or form.cleaned_data.get("DELETE"):
                continue
            cd = form.cleaned_data
            label = cd.get("label")
            if not label:
                continue
            start, end = cd.get("start"), cd.get("end")
            if start and end and start > end:
                raise ValidationError("A period's end date must not be before its start date.")
            if not label.group.is_partition:
                continue
            periods = per_group.setdefault(label.group_id, [])
            for prev_start, prev_end in periods:
                if ChannelLabel._overlaps(start, end, prev_start, prev_end):
                    raise ValidationError("Label periods within a partition group must not overlap.")
            periods.append((start, end))


class ChannelLabelInline(admin.TabularInline):
    model = ChannelLabel
    formset = ChannelLabelInlineFormSet
    extra = 0


@admin.register(Channel)
class ChannelAdmin(admin.ModelAdmin):
    date_hierarchy = "date"
    inlines = [ChannelLabelInline]
    list_display = (
        "__str__",
        "thumb",
        "in_degree",
        "out_degree",
        "participants_count",
        "messages_count",
        "date",
        "telegram_url",
        "current_org",
    )
    list_filter = ("channel_labels__label__is_in_target", "broadcast", "channel_labels__label", "groups")
    search_fields = ["username", "title", "about"]

    def get_queryset(self, request: HttpRequest) -> QuerySet[Channel]:
        return (
            super()
            .get_queryset(request)
            .annotate(_messages_count=Count("message_set", distinct=True))
            .prefetch_related(
                "channel_labels__label",
                Prefetch("profilepicture_set", queryset=ProfilePicture.objects.order_by("-date")),
            )
        )

    @admin.display(description="Org (now)")
    def current_org(self, obj: Channel) -> str:
        org = obj.current_label
        return org.name if org else "—"

    @admin.display(description="Msg")
    def messages_count(self, obj: Channel) -> int:
        return obj._messages_count  # type: ignore[attr-defined]

    @admin.display(description="Link")
    def telegram_url(self, obj: Channel) -> str:
        return format_html(
            "<a href='{}' target='_blank'>{}</a>",
            obj.telegram_url,
            obj.username,
        )

    @admin.display(description="Img")
    def thumb(self, obj: Channel) -> str:
        pic = next(iter(obj.profilepicture_set.all()), None)
        # display_url returns the static thumbnail for video avatars (or empty
        # when none was captured) so the admin list never renders an mp4 file
        # inside an <img> tag.
        src = pic.display_url if pic else ""
        if not src:
            return ""
        return format_html("<img width='60' src='{}'>", src)


@admin.register(Message)
class MessageAdmin(admin.ModelAdmin):
    date_hierarchy = "date"
    list_display = ("__str__", "thumb", "date", "telegram_url", "short_text", "forwards", "views", "is_lost")
    list_filter = ("is_lost",)
    search_fields = ["message"]

    def get_queryset(self, request: HttpRequest) -> QuerySet[Message]:
        return (
            super()
            .get_queryset(request)
            .select_related("channel")
            .prefetch_related(Prefetch("messagepicture_set", queryset=MessagePicture.objects.order_by("-date")))
        )

    @admin.display(description="Text")
    def short_text(self, obj: Message) -> str:
        return obj.message[:100] if obj.message else ""

    @admin.display(description="Link")
    def telegram_url(self, obj: Message) -> str:
        # Message.telegram_url is already a full https:// URL — prefixing another
        # scheme would produce the unreachable href "https://https://t.me/…".
        return format_html(
            "<a href='{}' target='_blank'>{}</a>",
            obj.telegram_url,
            obj.telegram_url,
        )

    @admin.display(description="Img")
    def thumb(self, obj: Message) -> str:
        pic = next(iter(obj.messagepicture_set.all()), None)
        src = pic.picture.url if (pic and pic.picture) else ""
        if not src:
            return ""
        return format_html("<img width='60' src='{}'>", src)


@admin.register(SearchTerm)
class SearchTermAdmin(admin.ModelAdmin):
    list_display = ("word", "last_check")
    fieldsets = ((None, {"fields": ("word",)}),)


@admin.register(ChannelGroup)
class ChannelGroupAdmin(admin.ModelAdmin):
    list_display = ("name", "channel_count", "description")
    search_fields = ("name",)
    filter_horizontal = ("channels",)

    def get_queryset(self, request: HttpRequest) -> QuerySet[ChannelGroup]:
        return super().get_queryset(request).annotate(_channel_count=Count("channels"))

    @admin.display(description="Channels")
    def channel_count(self, obj: ChannelGroup) -> int:
        return obj._channel_count  # type: ignore[attr-defined]


class LabelInline(admin.TabularInline):
    model = Label
    extra = 0


@admin.register(LabelGroup)
class LabelGroupAdmin(admin.ModelAdmin):
    list_display = ("name", "color", "is_partition", "is_primary", "label_count")
    list_editable = ["color", "is_partition"]
    inlines = [LabelInline]

    def get_queryset(self, request: HttpRequest) -> QuerySet[LabelGroup]:
        return super().get_queryset(request).annotate(_label_count=Count("labels"))

    @admin.display(description="Labels")
    def label_count(self, obj: LabelGroup) -> int:
        return obj._label_count  # type: ignore[attr-defined]


@admin.register(Label)
class LabelAdmin(admin.ModelAdmin):
    list_display = ("name", "group", "color", "is_in_target")
    list_editable = ["color", "is_in_target"]
    list_filter = ("group", "is_in_target")
    search_fields = ("name",)


@admin.register(Project)
class ProjectAdmin(admin.ModelAdmin):
    list_display = ("title",)

    # Singleton: never offer "add another" once the row exists, and never allow
    # deletion — the row is the project's identity, edited from the Manage panel.
    def has_add_permission(self, request: HttpRequest) -> bool:
        return not Project.objects.exists()

    def has_delete_permission(self, request: HttpRequest, obj=None) -> bool:
        return False


class PollAnswerInline(admin.TabularInline):
    model = PollAnswer
    extra = 0
    readonly_fields = ("option", "text", "voters", "correct")


@admin.register(Poll)
class PollAdmin(admin.ModelAdmin):
    list_display = ("__str__", "question", "quiz", "closed", "total_voters", "close_date")
    list_filter = ("quiz", "closed")
    search_fields = ("question",)
    inlines = [PollAnswerInline]
    raw_id_fields = ("message",)
