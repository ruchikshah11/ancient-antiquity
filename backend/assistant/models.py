from django.conf import settings
from django.db import models


class AssistantLog(models.Model):
    """One visitor message answered (or refused) by the AI assistant.

    Deliberately minimal: no message content is stored, only who (user or a salted IP hash), when and the
    token usage. The rows double as the per-day message counter behind ASSISTANT_DAILY_MESSAGE_LIMIT.
    """

    class Outcome(models.TextChoices):
        OK = "ok", "Answered"
        ERROR = "error", "API error"
        REFUSED = "refused", "Declined by the model"

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="assistant_logs"
    )
    ip_hash = models.CharField(max_length=64, db_index=True, blank=True)
    lang = models.CharField(max_length=5, blank=True)
    model = models.CharField(max_length=60, blank=True)
    outcome = models.CharField(max_length=8, choices=Outcome.choices, default=Outcome.OK)
    tokens_in = models.PositiveIntegerField(default=0, help_text="Uncached input tokens")
    tokens_out = models.PositiveIntegerField(default=0)
    cache_read_tokens = models.PositiveIntegerField(default=0)
    cache_write_tokens = models.PositiveIntegerField(default=0)
    tool_calls = models.PositiveSmallIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        who = self.user_id and f"user {self.user_id}" or f"ip {self.ip_hash[:8]}"
        return f"{who} {self.created_at:%Y-%m-%d %H:%M} ({self.tokens_in}+{self.tokens_out} tokens)"
