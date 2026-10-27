from django.contrib import admin

from .models import AssistantLog


@admin.register(AssistantLog)
class AssistantLogAdmin(admin.ModelAdmin):
    list_display = ("created_at", "user", "lang", "model", "outcome", "tokens_in", "tokens_out", "cache_read_tokens",
                    "tool_calls")
    list_filter = ("outcome", "lang", "model")
    date_hierarchy = "created_at"
    readonly_fields = [f.name for f in AssistantLog._meta.fields]

    def has_add_permission(self, request):
        return False
