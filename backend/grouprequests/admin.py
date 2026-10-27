from django.contrib import admin

from .models import GroupRequest


@admin.register(GroupRequest)
class GroupRequestAdmin(admin.ModelAdmin):
    list_display = ("id", "organisation_name", "museum", "preferred_date", "participants", "status", "payment_mode", "created_at")
    list_filter = ("status", "payment_mode", "group_type", "museum")
    search_fields = ("organisation_name", "contact_name", "contact_email", "contact_phone", "museum__name")
    raw_id_fields = ("requester", "museum", "decided_by")
    date_hierarchy = "preferred_date"
