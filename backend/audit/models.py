from django.conf import settings
from django.db import models


class AuditEntry(models.Model):
    """One recorded action: a panel user's change through the API, or a sign-in attempt."""

    class Action(models.TextChoices):
        CREATE = "create", "Create"
        UPDATE = "update", "Update"
        DELETE = "delete", "Delete"
        LOGIN = "login", "Login"
        LOGIN_FAILED = "login_failed", "Login failed"
        OTHER = "other", "Other"

    at = models.DateTimeField(auto_now_add=True, db_index=True)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="audit_entries"
    )
    ip = models.GenericIPAddressField(null=True, blank=True)
    method = models.CharField(max_length=10, blank=True)
    path = models.CharField(max_length=500, blank=True)
    action = models.CharField(max_length=15, choices=Action.choices, default=Action.OTHER, db_index=True)
    object_repr = models.CharField(max_length=255, blank=True)
    status_code = models.PositiveSmallIntegerField(null=True, blank=True)
    changes = models.JSONField(default=dict, blank=True, help_text="Request data with secrets removed")

    class Meta:
        ordering = ("-at", "-id")
        verbose_name = "audit entry"
        verbose_name_plural = "audit log"

    def __str__(self):
        return f"{self.at:%Y-%m-%d %H:%M} {self.user or '-'} {self.action} {self.path}"
