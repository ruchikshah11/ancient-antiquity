from django.contrib import admin

from .models import NotificationLog, PushSubscription


@admin.register(NotificationLog)
class NotificationLogAdmin(admin.ModelAdmin):
    list_display = ("created_at", "channel", "kind", "recipient", "booking", "status")
    list_filter = ("channel", "kind", "status")
    search_fields = ("recipient", "subject", "booking__reference", "user__email")
    date_hierarchy = "created_at"
    readonly_fields = [f.name for f in NotificationLog._meta.fields]
    list_select_related = ("booking",)

    def has_add_permission(self, request):
        return False  # logs are written by the system only


@admin.register(PushSubscription)
class PushSubscriptionAdmin(admin.ModelAdmin):
    list_display = ("created_at", "user", "user_agent")
    search_fields = ("user__email", "endpoint", "user_agent")
    readonly_fields = [f.name for f in PushSubscription._meta.fields]
    list_select_related = ("user",)

    def has_add_permission(self, request):
        return False  # created by browsers via the subscribe endpoint
