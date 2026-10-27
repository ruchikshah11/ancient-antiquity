from django.contrib import admin

from .models import School, SchoolTrip


@admin.register(School)
class SchoolAdmin(admin.ModelAdmin):
    list_display = ("name", "city", "state", "board", "status", "owner", "created_at")
    list_filter = ("status", "board", "state")
    search_fields = ("name", "city", "udise_code", "contact_email", "owner__email")
    raw_id_fields = ("owner", "verified_by")


@admin.register(SchoolTrip)
class SchoolTripAdmin(admin.ModelAdmin):
    list_display = ("reference", "school", "museum", "preferred_date", "students", "teachers", "status", "quoted_amount")
    list_filter = ("status", "slot_preference")
    search_fields = ("school__name", "museum__name")
    raw_id_fields = ("school", "requested_by", "museum", "booking", "decided_by")
