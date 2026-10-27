from django.contrib import admin

from .models import EmailOptOut, FunnelEvent, RecoveryEmail


@admin.register(FunnelEvent)
class FunnelEventAdmin(admin.ModelAdmin):
    list_display = ("created_at", "event", "museum", "session_id", "user", "booking", "utm_source")
    list_filter = ("event", "utm_source")
    date_hierarchy = "created_at"
    raw_id_fields = ("user", "museum", "booking")


@admin.register(RecoveryEmail)
class RecoveryEmailAdmin(admin.ModelAdmin):
    list_display = ("sent_at", "booking", "email", "converted_booking")
    search_fields = ("email", "booking__reference")
    raw_id_fields = ("booking", "converted_booking")


@admin.register(EmailOptOut)
class EmailOptOutAdmin(admin.ModelAdmin):
    list_display = ("email", "created_at")
    search_fields = ("email",)
