from django.contrib import admin

from .models import Event, EventType


@admin.register(EventType)
class EventTypeAdmin(admin.ModelAdmin):
    list_display = ["name", "description"]
    search_fields = ["name"]


@admin.register(Event)
class EventAdmin(admin.ModelAdmin):
    list_display = ["date", "subject", "action"]
    list_filter = ["action"]
    search_fields = ["subject"]
    date_hierarchy = "date"
