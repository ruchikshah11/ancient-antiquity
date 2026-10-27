from django.contrib import admin

from .models import (
    Category, City, Gate, Museum, MuseumImage, PlaceClosure, PriceRule, Review, ReviewPhoto, SiteSettings, State,
    TicketType, TimeSlot,
)


@admin.register(State)
class StateAdmin(admin.ModelAdmin):
    list_display = ("name", "code", "is_union_territory")
    search_fields = ("name", "code")


@admin.register(City)
class CityAdmin(admin.ModelAdmin):
    list_display = ("name", "state")
    list_filter = ("state",)
    search_fields = ("name",)


@admin.register(Category)
class CategoryAdmin(admin.ModelAdmin):
    list_display = ("name", "slug")
    prepopulated_fields = {"slug": ("name",)}


class MuseumImageInline(admin.TabularInline):
    model = MuseumImage
    extra = 0


class TicketTypeInline(admin.TabularInline):
    model = TicketType
    extra = 0


class TimeSlotInline(admin.TabularInline):
    model = TimeSlot
    extra = 0


class PriceRuleInline(admin.TabularInline):
    model = PriceRule
    extra = 0


@admin.register(Museum)
class MuseumAdmin(admin.ModelAdmin):
    list_display = ("name", "place_type", "city", "category", "allow_individual", "allow_groups", "is_featured", "is_active", "info_verified")
    list_editable = ("allow_groups", "allow_individual")
    list_filter = ("place_type", "is_active", "is_featured", "info_verified", "category", "city__state")
    search_fields = ("name", "city__name", "city__state__name")
    autocomplete_fields = ("city",)
    filter_horizontal = ("staff",)
    readonly_fields = ("info_verified_at", "info_verified_by")
    inlines = [TicketTypeInline, TimeSlotInline, PriceRuleInline, MuseumImageInline]


class ReviewPhotoInline(admin.TabularInline):
    model = ReviewPhoto
    extra = 0
    fields = ("image", "status", "created_at")
    readonly_fields = ("created_at",)


@admin.register(Review)
class ReviewAdmin(admin.ModelAdmin):
    inlines = [ReviewPhotoInline]
    list_display = ("museum", "user", "rating", "title", "is_published", "created_at")
    list_filter = ("rating", "is_published")
    list_editable = ("is_published",)
    search_fields = ("museum__name", "user__email", "title", "comment")


@admin.register(PlaceClosure)
class PlaceClosureAdmin(admin.ModelAdmin):
    list_display = ("start_date", "end_date", "museum", "reason", "all_day", "created_by")
    list_filter = ("all_day",)
    search_fields = ("reason", "museum__name")
    autocomplete_fields = ("museum",)
    filter_horizontal = ("slots",)
    readonly_fields = ("created_by", "created_at")
    date_hierarchy = "start_date"


@admin.register(PriceRule)
class PriceRuleAdmin(admin.ModelAdmin):
    list_display = ("name", "museum", "ticket_type", "adjustment_type", "value", "start_date", "end_date",
                    "weekdays", "priority", "is_active")
    list_filter = ("is_active", "adjustment_type")
    search_fields = ("name", "museum__name")
    autocomplete_fields = ("museum",)


@admin.register(Gate)
class GateAdmin(admin.ModelAdmin):
    list_display = ("name", "museum", "sort_order", "is_active")
    list_filter = ("is_active",)
    search_fields = ("name", "museum__name")
    autocomplete_fields = ("museum",)


@admin.register(ReviewPhoto)
class ReviewPhotoAdmin(admin.ModelAdmin):
    list_display = ("id", "review", "status", "created_at")
    list_filter = ("status",)
    list_editable = ("status",)
    raw_id_fields = ("review",)


@admin.register(SiteSettings)
class SiteSettingsAdmin(admin.ModelAdmin):
    list_display = ("__str__", "individual_bookings_enabled", "group_bookings_enabled", "group_requests_enabled",
                    "school_trips_enabled", "events_enabled", "passes_enabled", "updated_at")

    def has_add_permission(self, request):
        return not SiteSettings.objects.exists()

    def has_delete_permission(self, request, obj=None):
        return False
