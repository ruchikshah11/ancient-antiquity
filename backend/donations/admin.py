from django.contrib import admin

from .models import Donation, ReceiptCounter


@admin.register(Donation)
class DonationAdmin(admin.ModelAdmin):
    list_display = ("reference", "receipt_number", "donor_name", "amount", "museum", "wants_80g", "status", "paid_at")
    list_filter = ("status", "wants_80g", "gateway")
    search_fields = ("reference", "receipt_number", "donor_name", "donor_email", "donor_pan")
    autocomplete_fields = ("museum",)
    raw_id_fields = ("user",)
    readonly_fields = ("reference", "receipt_number", "receipt_fy", "receipt_seq", "created_at")
    date_hierarchy = "created_at"


@admin.register(ReceiptCounter)
class ReceiptCounterAdmin(admin.ModelAdmin):
    list_display = ("financial_year", "last_number")
