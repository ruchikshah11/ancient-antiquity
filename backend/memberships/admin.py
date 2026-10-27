from django.contrib import admin

from .models import Membership, MembershipPlan


@admin.register(MembershipPlan)
class MembershipPlanAdmin(admin.ModelAdmin):
    list_display = ("name", "price", "duration_days", "discount_percent", "free_entry", "max_visitors_per_booking", "is_active")
    list_filter = ("is_active", "free_entry")
    filter_horizontal = ("places",)


@admin.register(Membership)
class MembershipAdmin(admin.ModelAdmin):
    list_display = ("card_number", "user", "plan_name", "status", "starts_on", "ends_on", "total_amount")
    list_filter = ("status", "plan")
    search_fields = ("card_number", "user__email", "holder_name")
    list_select_related = ("user",)
