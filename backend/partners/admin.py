from django.contrib import admin

from .models import AgentPayment, AgentProfile, KioskDevice, PartnerAccount, Settlement


@admin.register(AgentProfile)
class AgentProfileAdmin(admin.ModelAdmin):
    list_display = ("company_name", "user", "status", "commission_percent", "credit_limit", "balance")
    list_filter = ("status",)
    search_fields = ("company_name", "user__email", "gstin")
    raw_id_fields = ("user", "approved_by")


@admin.register(AgentPayment)
class AgentPaymentAdmin(admin.ModelAdmin):
    list_display = ("agent", "amount", "reference", "received_on", "recorded_by")
    raw_id_fields = ("agent", "recorded_by")


@admin.register(PartnerAccount)
class PartnerAccountAdmin(admin.ModelAdmin):
    list_display = ("museum", "bank_name", "razorpay_account_id", "platform_fee_percent")
    raw_id_fields = ("museum",)


@admin.register(Settlement)
class SettlementAdmin(admin.ModelAdmin):
    list_display = ("museum", "period_start", "period_end", "gross_online", "net_payable", "status")
    list_filter = ("status",)
    raw_id_fields = ("museum", "approved_by", "created_by")


@admin.register(KioskDevice)
class KioskDeviceAdmin(admin.ModelAdmin):
    list_display = ("name", "user", "is_active")
    raw_id_fields = ("user",)
    filter_horizontal = ("museums",)
