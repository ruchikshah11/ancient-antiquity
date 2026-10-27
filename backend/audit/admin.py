import json

from django.contrib import admin
from django.utils.html import format_html

from .models import AuditEntry


@admin.register(AuditEntry)
class AuditEntryAdmin(admin.ModelAdmin):
    """Read-only: the audit log can be browsed but never edited or deleted from the admin site."""

    list_display = ("at", "user", "action", "method", "path", "status_code", "ip")
    list_filter = ("action", "method")
    search_fields = ("path", "object_repr", "user__email", "ip")
    date_hierarchy = "at"
    list_select_related = ("user",)
    fields = ("at", "user", "ip", "method", "path", "action", "object_repr", "status_code", "pretty_changes")
    readonly_fields = fields

    @admin.display(description="Changes")
    def pretty_changes(self, obj):
        return format_html("<pre style='white-space:pre-wrap'>{}</pre>", json.dumps(obj.changes, indent=2, ensure_ascii=False))

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
