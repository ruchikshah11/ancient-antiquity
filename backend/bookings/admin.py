from django.contrib import admin

from .models import Booking, BookingItem


class BookingItemInline(admin.TabularInline):
    model = BookingItem
    extra = 0
    readonly_fields = ("ticket_type", "ticket_name", "quantity", "unit_price")
    can_delete = False


@admin.register(Booking)
class BookingAdmin(admin.ModelAdmin):
    list_display = ("reference", "museum", "visit_date", "slot", "is_group", "total_visitors", "visitors_arrived",
                    "total_amount", "status")
    list_filter = ("status", "is_group", "group_type", "channel", "visit_date", "museum__city__state")
    search_fields = ("reference", "visitor_name", "visitor_email", "visitor_phone", "organisation_name", "museum__name")
    date_hierarchy = "visit_date"
    readonly_fields = ("reference", "created_at", "paid_at", "cancelled_at", "checked_in_at", "payment_id")
    inlines = [BookingItemInline]
