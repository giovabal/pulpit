from django.contrib import admin
from django.db.models import Count, Prefetch, QuerySet
from django.http import HttpRequest
from django.utils.html import format_html

from .models import (
    Channel,
    ChannelGroup,
    Message,
    MessagePicture,
    Organization,
    Poll,
    PollAnswer,
    ProfilePicture,
    SearchTerm,
)


@admin.register(Channel)
class ChannelAdmin(admin.ModelAdmin):
    date_hierarchy = "date"
    list_display = (
        "__str__",
        "thumb",
        "in_degree",
        "out_degree",
        "participants_count",
        "messages_count",
        "date",
        "telegram_url",
        "organization",
    )
    list_editable = ("organization",)
    list_filter = ("organization__is_interesting", "broadcast", "organization", "groups")
    search_fields = ["username", "title", "about"]

    def get_queryset(self, request: HttpRequest) -> QuerySet[Channel]:
        return (
            super()
            .get_queryset(request)
            .select_related("organization")
            .annotate(_messages_count=Count("message_set", distinct=True))
            .prefetch_related(Prefetch("profilepicture_set", queryset=ProfilePicture.objects.order_by("-date")))
        )

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
        src = pic.picture.url if pic else ""
        if not src:
            return ""
        return format_html("<img width='60' src='{}'>", src)


@admin.register(Message)
class MessageAdmin(admin.ModelAdmin):
    date_hierarchy = "date"
    list_display = ("__str__", "thumb", "date", "telegram_url", "short_text", "forwards", "views")
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
        return format_html(
            "<a href='https://{}' target='_blank'>{}</a>",
            obj.telegram_url,
            obj.telegram_url,
        )

    @admin.display(description="Img")
    def thumb(self, obj: Message) -> str:
        pic = next(iter(obj.messagepicture_set.all()), None)
        src = pic.picture.url if pic else ""
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


@admin.register(Organization)
class OrganizationAdmin(admin.ModelAdmin):
    list_display = ("name", "color", "is_interesting")
    list_editable = ["color", "is_interesting"]


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
