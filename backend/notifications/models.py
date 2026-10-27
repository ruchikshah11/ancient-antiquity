from django.conf import settings
from django.db import models


class NotificationLog(models.Model):
    """One attempt to email/text someone. Doubles as an audit trail and the source for resend rate limits."""

    class Channel(models.TextChoices):
        EMAIL = "email", "Email"
        SMS = "sms", "SMS"
        WHATSAPP = "whatsapp", "WhatsApp"
        PUSH = "push", "Web push"

    class Status(models.TextChoices):
        SENT = "sent", "Sent"
        FAILED = "failed", "Failed"
        SKIPPED = "skipped", "Skipped"

    booking = models.ForeignKey(
        "bookings.Booking", on_delete=models.SET_NULL, null=True, blank=True, related_name="notifications"
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="notifications"
    )
    channel = models.CharField(max_length=10, choices=Channel.choices)
    kind = models.CharField(max_length=30, db_index=True, help_text="confirmed, cancelled, resend, password_reset, reminder, reminder_soon")
    recipient = models.CharField(max_length=254, blank=True)
    subject = models.CharField(max_length=200, blank=True)
    status = models.CharField(max_length=7, choices=Status.choices, db_index=True)
    error = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.channel} {self.kind} -> {self.recipient or '-'} ({self.status})"


class PushSubscription(models.Model):
    """A browser's Web Push subscription (from PushManager.subscribe), used for visit reminders."""

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="push_subscriptions")
    endpoint = models.URLField(max_length=1000, unique=True)
    p256dh = models.CharField(max_length=200)
    auth = models.CharField(max_length=100)
    user_agent = models.CharField(max_length=300, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"Push subscription of {self.user} ({self.endpoint[:40]}...)"

    def as_subscription_info(self):
        return {"endpoint": self.endpoint, "keys": {"p256dh": self.p256dh, "auth": self.auth}}
