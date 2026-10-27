from django.contrib import admin

from .models import ComboPass, ComboPassSite, PassOrder, PassVisit


class ComboPassSiteInline(admin.TabularInline):
    model = ComboPassSite
    extra = 0
    autocomplete_fields = ("museum",)


@admin.register(ComboPass)
class ComboPassAdmin(admin.ModelAdmin):
    list_display = ("name", "validity_days", "price_indian", "price_foreign", "is_active", "featured")
    list_filter = ("is_active", "featured")
    search_fields = ("name",)
    prepopulated_fields = {"slug": ("name",)}
    inlines = [ComboPassSiteInline]


class PassVisitInline(admin.TabularInline):
    model = PassVisit
    extra = 0
    readonly_fields = ("museum", "visited_at", "admitted", "scanned_by", "scan_id", "offline", "gate")


@admin.register(PassOrder)
class PassOrderAdmin(admin.ModelAdmin):
    list_display = ("reference", "pass_name", "user", "start_date", "total_visitors", "total_amount", "status")
    list_filter = ("status", "combo_pass")
    search_fields = ("reference", "visitor_name", "visitor_email", "user__email")
    readonly_fields = ("reference", "created_at", "paid_at", "cancelled_at")
    inlines = [PassVisitInline]
