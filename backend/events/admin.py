from django.contrib import admin

from .models import Event, EventPrice, EventSession, WaitlistEntry


class EventPriceInline(admin.TabularInline):
    model = EventPrice
    extra = 0


@admin.register(Event)
class EventAdmin(admin.ModelAdmin):
    list_display = ("title", "museum", "kind", "is_active", "featured")
    list_filter = ("kind", "is_active", "featured")
    search_fields = ("title", "museum__name")
    inlines = [EventPriceInline]


@admin.register(EventSession)
class EventSessionAdmin(admin.ModelAdmin):
    list_display = ("event", "date", "start_time", "end_time", "capacity", "is_active")
    list_filter = ("is_active",)
    date_hierarchy = "date"


@admin.register(WaitlistEntry)
class WaitlistEntryAdmin(admin.ModelAdmin):
    list_display = ("user", "museum", "visit_date", "slot", "event_session", "quantity", "status", "created_at")
    list_filter = ("status",)
