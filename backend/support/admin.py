from django.contrib import admin

from .models import ContactMessage


@admin.register(ContactMessage)
class ContactMessageAdmin(admin.ModelAdmin):
    list_display = ("created_at", "name", "email", "topic", "place_slug", "status")
    list_filter = ("status", "topic", "created_at")
    list_editable = ("status",)
    search_fields = ("name", "email", "phone", "message", "place_slug", "booking_reference")
    readonly_fields = ("created_at", "updated_at", "ip_address", "user")
    date_hierarchy = "created_at"
