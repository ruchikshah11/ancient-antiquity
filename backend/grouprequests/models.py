from django.conf import settings
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models

from bookings.models import Booking
from museums.models import Museum


class GroupRequest(models.Model):
    """A visit request for a group larger than GROUP_MAX_SIZE. Staff review it, split it across slots and
    approve it, which creates one pending booking per slot (paid online or by bank transfer / invoice)."""

    class Status(models.TextChoices):
        SUBMITTED = "submitted", "Submitted"
        UNDER_REVIEW = "under_review", "Under review"
        APPROVED = "approved", "Approved - awaiting payment"
        DECLINED = "declined", "Declined"
        PAID = "paid", "Paid"
        CANCELLED = "cancelled", "Cancelled"
        EXPIRED = "expired", "Expired"

    class PreferredTime(models.TextChoices):
        MORNING = "morning", "Morning"
        AFTERNOON = "afternoon", "Afternoon"
        ANY = "any", "Any time"

    class PaymentMode(models.TextChoices):
        ONLINE = "online", "Online payment"
        INVOICE = "invoice", "Invoice / bank transfer"

    OPEN = (Status.SUBMITTED, Status.UNDER_REVIEW)

    requester = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="group_requests")
    museum = models.ForeignKey(Museum, on_delete=models.PROTECT, related_name="group_requests")
    preferred_date = models.DateField(db_index=True)
    alternative_date = models.DateField(null=True, blank=True)
    preferred_time = models.CharField(max_length=10, choices=PreferredTime.choices, default=PreferredTime.ANY)
    group_type = models.CharField(max_length=15, choices=Booking.GroupType.choices)
    organisation_name = models.CharField(max_length=150)
    contact_name = models.CharField(max_length=120)
    contact_email = models.EmailField()
    contact_phone = models.CharField(max_length=15)
    participants = models.PositiveIntegerField(validators=[MinValueValidator(61), MaxValueValidator(1000)])
    escorts = models.PositiveSmallIntegerField(default=0, help_text="Escorts / teachers requested")
    needs_guide = models.BooleanField(default=False)
    notes = models.TextField(blank=True)

    status = models.CharField(max_length=12, choices=Status.choices, default=Status.SUBMITTED, db_index=True)
    staff_notes = models.TextField(blank=True, help_text="Decline reason or internal notes")
    quoted_total = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    discount_percent = models.PositiveSmallIntegerField(null=True, blank=True, validators=[MaxValueValidator(100)])
    approved_date = models.DateField(null=True, blank=True, help_text="Visit date the request was approved for")
    decided_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    decided_at = models.DateTimeField(null=True, blank=True)
    payment_mode = models.CharField(max_length=10, choices=PaymentMode.choices, blank=True)
    pay_by = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"GR-{self.pk} {self.organisation_name} ({self.participants})"

    @property
    def reference(self):
        return f"GR-{self.pk:05d}" if self.pk else ""
