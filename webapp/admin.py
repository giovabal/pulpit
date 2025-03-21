from django.contrib import admin
from django.utils.html import format_html

from .models import Channel, Message, Organization, SearchTerm


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
    search_fields = ["username", "title"]

    @admin.display(description="Msg")
    def messages_count(self, obj):
        return obj.message_set.all().count()

    @admin.display(description="Link")
    def telegram_url(self, obj):
        return format_html(f"<a href='{obj.telegram_url}' target='_blank'>{obj.username}</a>")

    @admin.display(description="Img")
    def thumb(self, obj):
        src = obj.profile_picture.picture.url if obj.profile_picture else ""
        return format_html(f"<img width='60' src='{src}'>")


@admin.register(Message)
class MessageAdmin(admin.ModelAdmin):
    date_hierarchy = "date"
    list_display = ("__str__", "thumb", "date", "telegram_url", "short_text", "forwards", "views")
    search_fields = ["message"]

    @admin.display(description="Text")
    def short_text(self, obj):
        return obj.message[:100] if obj.message else ""

    @admin.display(description="Link")
    def telegram_url(self, obj):
        return format_html(f"<a href='https://{obj.telegram_url}' target='_blank'>{obj.telegram_url}</a>")

    @admin.display(description="Img")
    def thumb(self, obj):
        src = obj.message_picture.picture.url if obj.message_picture else ""
        return format_html(f"<img width='60' src='{src}'>")


@admin.register(SearchTerm)
class SearchTermAdmin(admin.ModelAdmin):
    list_display = ("word", "last_check")
    fieldsets = ((None, {"fields": ("word",)}),)


@admin.register(Organization)
class OrganizationAdmin(admin.ModelAdmin):
    list_display = ("name", "color")
    list_editable = ["color"]
