from django.contrib import admin

from .models import Favourite, Trip, TripStop


@admin.register(Favourite)
class FavouriteAdmin(admin.ModelAdmin):
    list_display = ("user", "museum", "created_at")
    raw_id_fields = ("user", "museum")


class TripStopInline(admin.TabularInline):
    model = TripStop
    extra = 0
    raw_id_fields = ("museum",)


@admin.register(Trip)
class TripAdmin(admin.ModelAdmin):
    list_display = ("title", "user", "start_date", "end_date", "created_at")
    raw_id_fields = ("user",)
    inlines = [TripStopInline]
