from django.contrib import admin

from .models import AddOn


@admin.register(AddOn)
class AddOnAdmin(admin.ModelAdmin):
    list_display = ("name", "museum", "kind", "price", "per", "daily_stock", "is_active", "sort")
    list_filter = ("kind", "per", "is_active")
    search_fields = ("name", "museum__name")
    list_select_related = ("museum",)
