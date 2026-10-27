from django.conf import settings
from django.db import models


class FunnelEvent(models.Model):
    """One step of the visitor booking funnel, sent by the website (anonymous session id, no personal data).

    Steps the server already knows from Booking rows (booking created, payment started, paid, cancelled) are
    derived from those rows in the funnel report rather than trusted from the client.
    """

    class Event(models.TextChoices):
        VIEW_PLACE = "view_place", "Viewed a place"
        SELECT_SLOT = "select_slot", "Selected a slot"
        START_BOOKING = "start_booking", "Started a booking"
        VIEW_CHECKOUT = "view_checkout", "Opened checkout"
        PAYMENT_STARTED = "payment_started", "Started payment"
        PAID = "paid", "Paid"
        CANCELLED = "cancelled", "Cancelled"

    session_id = models.CharField(max_length=64, db_index=True, help_text="Random id kept in the visitor's browser")
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="funnel_events"
    )
    event = models.CharField(max_length=20, choices=Event.choices, db_index=True)
    museum = models.ForeignKey(
        "museums.Museum", on_delete=models.CASCADE, null=True, blank=True, related_name="funnel_events"
    )
    booking = models.ForeignKey(
        "bookings.Booking", on_delete=models.SET_NULL, null=True, blank=True, related_name="funnel_events"
    )
    utm_source = models.CharField(max_length=60, blank=True)
    utm_medium = models.CharField(max_length=60, blank=True)
    utm_campaign = models.CharField(max_length=80, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["event", "created_at"]), models.Index(fields=["museum", "event"])]

    def __str__(self):
        return f"{self.event} {self.session_id[:8]} {self.created_at:%Y-%m-%d %H:%M}"


class EmailOptOut(models.Model):
    """Addresses that asked not to receive booking-recovery (marketing-style) emails."""

    email = models.EmailField(unique=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "email opt-out"

    def save(self, *args, **kwargs):
        self.email = self.email.strip().lower()
        super().save(*args, **kwargs)

    @classmethod
    def is_opted_out(cls, email):
        return cls.objects.filter(email=(email or "").strip().lower()).exists()

    def __str__(self):
        return self.email


class RecoveryEmail(models.Model):
    """A "your tickets are waiting" email sent for an abandoned (unpaid) booking. One per booking at most."""

    booking = models.OneToOneField("bookings.Booking", on_delete=models.CASCADE, related_name="recovery_email")
    email = models.EmailField()
    sent_at = models.DateTimeField(auto_now_add=True, db_index=True)
    converted_booking = models.ForeignKey(
        "bookings.Booking", on_delete=models.SET_NULL, null=True, blank=True, related_name="+",
        help_text="Paid booking by the same visitor for the same place within 7 days of the email",
    )

    class Meta:
        ordering = ["-sent_at"]

    def __str__(self):
        return f"Recovery {self.booking_id} -> {self.email}"
