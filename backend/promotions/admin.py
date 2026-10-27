from django.contrib import admin

from .models import GiftVoucher, PromoCode, PromoRedemption, VoucherRedemption


@admin.register(PromoCode)
class PromoCodeAdmin(admin.ModelAdmin):
    list_display = ("code", "discount_type", "value", "scope", "applies_to", "is_active", "valid_to")
    list_filter = ("is_active", "discount_type", "scope")
    search_fields = ("code", "description")
    filter_horizontal = ("museums",)


@admin.register(GiftVoucher)
class GiftVoucherAdmin(admin.ModelAdmin):
    list_display = ("code", "initial_value", "balance", "recipient_name", "valid_until", "is_active")
    list_filter = ("is_active",)
    search_fields = ("code", "recipient_name", "recipient_email", "purchaser_name", "purchaser_email")
    readonly_fields = ("code",)


admin.site.register(PromoRedemption)
admin.site.register(VoucherRedemption)
