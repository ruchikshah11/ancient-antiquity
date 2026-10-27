from django.contrib import admin, messages
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin

from .models import LoginOTP, User


@admin.register(User)
class UserAdmin(BaseUserAdmin):
    ordering = ("-date_joined",)
    list_display = ("email", "first_name", "last_name", "phone", "role", "is_active", "totp_enabled")
    list_filter = ("role", "is_active", "is_staff", "totp_enabled")
    search_fields = ("email", "first_name", "last_name", "phone")
    fieldsets = (
        (None, {"fields": ("email", "password")}),
        ("Personal info", {"fields": ("first_name", "last_name", "phone")}),
        ("Role & access", {"fields": ("role", "is_active", "is_staff", "is_superuser", "groups")}),
        ("Sign-in", {"fields": ("google_sub", "totp_enabled")}),
        ("Dates", {"fields": ("last_login", "date_joined")}),
    )
    readonly_fields = ("google_sub", "totp_enabled")
    add_fieldsets = (
        (None, {"classes": ("wide",), "fields": ("email", "password1", "password2", "role")}),
    )
    actions = ["reset_two_factor"]

    @admin.action(description="Turn off two-step verification (lost phone)")
    def reset_two_factor(self, request, queryset):
        n = queryset.filter(totp_enabled=True).update(totp_enabled=False, totp_secret="", totp_backup_codes=[])
        self.message_user(request, f"Two-step verification turned off for {n} user(s).", messages.SUCCESS)


@admin.register(LoginOTP)
class LoginOTPAdmin(admin.ModelAdmin):
    """Read-only view of sign-in codes (only hashes are stored)."""

    list_display = ("destination", "channel", "created_at", "expires_at", "attempts", "used_at")
    list_filter = ("channel",)
    search_fields = ("destination",)
    exclude = ("code_hash",)

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False
