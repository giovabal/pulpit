from django.contrib import admin
from django.db.models import Count, Prefetch, QuerySet
from django.http import HttpRequest
from django.utils.html import format_html

from .models import Channel, Message, Organization, ProfilePicture, SearchTerm


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
    list_filter = ("organization__is_interesting", "broadcast", "organization")
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
        # profilepicture_set is prefetched ordered by date descending; first = most recent
        pics = list(obj.profilepicture_set.all())
        pic = pics[0] if pics else None
        src = pic.picture.url if pic else ""
        if not src:
            return ""
        return format_html("<img width='60' src='{}'>", src)


@admin.register(Message)
class MessageAdmin(admin.ModelAdmin):
    date_hierarchy = "date"
    list_display = ("__str__", "thumb", "date", "telegram_url", "short_text", "forwards", "views")
    search_fields = ["message"]

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
        src = obj.message_picture.picture.url if obj.message_picture else ""
        if not src:
            return ""
        return format_html("<img width='60' src='{}'>", src)


@admin.register(SearchTerm)
class SearchTermAdmin(admin.ModelAdmin):
    list_display = ("word", "last_check")
    fieldsets = ((None, {"fields": ("word",)}),)


@admin.register(Organization)
class OrganizationAdmin(admin.ModelAdmin):
    list_display = ("name", "color")
    list_editable = ["color"]
