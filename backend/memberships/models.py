"""Annual membership ("Heritage Card"): a paid plan that takes a discount off entry tickets for a year.

A member booking online at an eligible place gets the plan's discount (100% with free entry) on up to
max_visitors_per_booking tickets, the most expensive first (bookings.services.create_booking). Buying a card
works like buying a combo pass: a pending Membership, then Razorpay or the demo gateway.
"""
import secrets
from datetime import timedelta
from decimal import Decimal

from django.conf import settings
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.utils import timezone
from django.utils.text import slugify

from museums.models import Museum


def generate_card_number():
    # e.g. AAM-7K2Q-9M4X (same alphabet as booking references: no 0/O/1/I)
    alphabet = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
    part = lambda: "".join(secrets.choice(alphabet) for _ in range(4))  # noqa: E731
    return f"AAM-{part()}-{part()}"


class MembershipPlan(models.Model):
    name = models.CharField(max_length=100)
    slug = models.SlugField(max_length=120, unique=True, blank=True)
    description = models.TextField(blank=True)
    price = models.DecimalField(max_digits=8, decimal_places=2, validators=[MinValueValidator(Decimal("0"))])
    duration_days = models.PositiveSmallIntegerField(default=365, validators=[MinValueValidator(1)])
    discount_percent = models.PositiveSmallIntegerField(
        default=0, validators=[MaxValueValidator(100)], help_text="Off entry tickets (ignored when free entry is on)"
    )
    free_entry = models.BooleanField(default=False, help_text="Covered tickets are free")
    places = models.ManyToManyField(
        Museum, blank=True, related_name="membership_plans", help_text="Places where the card works (none = all places)"
    )
    max_visitors_per_booking = models.PositiveSmallIntegerField(
        default=1, validators=[MinValueValidator(1)], help_text="Tickets per booking covered by the benefit (member + guests)"
    )
    is_active = models.BooleanField(default=True)
    sort = models.PositiveSmallIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["sort", "price", "id"]

    def save(self, *args, **kwargs):
        if not self.slug:
            base = slugify(self.name)[:110] or "plan"
            slug, n = base, 2
            while MembershipPlan.objects.filter(slug=slug).exclude(pk=self.pk).exists():
                slug, n = f"{base}-{n}", n + 1
            self.slug = slug
        super().save(*args, **kwargs)

    @property
    def benefit_percent(self):
        return 100 if self.free_entry else self.discount_percent

    def __str__(self):
        return self.name


class Membership(models.Model):
    class Status(models.TextChoices):
        PENDING = "pending", "Pending payment"
        ACTIVE = "active", "Active"
        EXPIRED = "expired", "Expired"
        CANCELLED = "cancelled", "Cancelled"

    class RefundStatus(models.TextChoices):
        NONE = "", "No refund"
        PENDING = "pending", "Refund initiated"
        PROCESSED = "processed", "Refunded"
        FAILED = "failed", "Refund failed"

    card_number = models.CharField(max_length=13, unique=True, default=generate_card_number, editable=False)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="memberships")
    plan = models.ForeignKey(MembershipPlan, on_delete=models.PROTECT, related_name="memberships")
    # Snapshots: later plan edits don't change cards already bought (the plan's places still apply).
    plan_name = models.CharField(max_length=100)
    discount_percent = models.PositiveSmallIntegerField(default=0)
    free_entry = models.BooleanField(default=False)
    max_visitors_per_booking = models.PositiveSmallIntegerField(default=1)
    duration_days = models.PositiveSmallIntegerField(default=365)
    holder_name = models.CharField(max_length=120)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.PENDING, db_index=True)
    starts_on = models.DateField(null=True, blank=True, help_text="Set when paid")
    ends_on = models.DateField(null=True, blank=True, db_index=True, help_text="Last valid day")
    total_amount = models.DecimalField(max_digits=10, decimal_places=2)
    payment_method = models.CharField(max_length=15, blank=True, help_text="Same values as Booking.payment_method")
    payment_id = models.CharField(max_length=40, blank=True)
    gateway = models.CharField(max_length=12, blank=True, help_text="razorpay or mock")
    gateway_order_id = models.CharField(max_length=40, blank=True, db_index=True)
    refund_id = models.CharField(max_length=40, blank=True)
    refund_amount = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    refund_status = models.CharField(max_length=10, choices=RefundStatus.choices, blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)
    paid_at = models.DateTimeField(null=True, blank=True)
    cancelled_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return self.card_number

    # Same name as PassOrder/Booking so the shared Razorpay helpers read naturally.
    @property
    def reference(self):
        return self.card_number

    @property
    def benefit_percent(self):
        return 100 if self.free_entry else self.discount_percent

    @property
    def hold_expires_at(self):
        if self.status != self.Status.PENDING:
            return None
        return self.created_at + timedelta(minutes=settings.BOOKING_HOLD_MINUTES)

    @property
    def is_hold_expired(self):
        expires = self.hold_expires_at
        return expires is not None and timezone.now() >= expires

    def is_valid_on(self, day):
        return (
            self.status == self.Status.ACTIVE and self.starts_on is not None
            and self.starts_on <= day <= self.ends_on
        )
