"""Combo passes: one ticket (and one QR) for several places, used within a few days.

A pass does not reserve a time slot: the party may enter each included place once, at any open time,
between the order's start_date and start_date + validity_days - 1.
"""
import secrets
from datetime import datetime, timedelta
from decimal import Decimal

from django.conf import settings
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.utils import timezone
from django.utils.text import slugify

from museums.models import Museum

# Visitor categories a pass is priced for, in display order.
CATEGORIES = ("indian", "foreign", "student", "child")


def generate_pass_reference():
    # e.g. AP-7K2Q9M4X (same alphabet as booking references: no 0/O/1/I)
    alphabet = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
    return "AP-" + "".join(secrets.choice(alphabet) for _ in range(8))


class ComboPass(models.Model):
    name = models.CharField(max_length=120)
    slug = models.SlugField(max_length=140, unique=True, blank=True)
    description = models.TextField(blank=True)
    image_url = models.URLField(max_length=500, blank=True)
    museums = models.ManyToManyField(Museum, through="ComboPassSite", related_name="combo_passes")
    price_indian = models.DecimalField(max_digits=8, decimal_places=2, default=0, validators=[MinValueValidator(Decimal("0"))])
    price_foreign = models.DecimalField(max_digits=8, decimal_places=2, default=0, validators=[MinValueValidator(Decimal("0"))])
    price_student = models.DecimalField(max_digits=8, decimal_places=2, default=0, validators=[MinValueValidator(Decimal("0"))])
    price_child = models.DecimalField(max_digits=8, decimal_places=2, default=0, validators=[MinValueValidator(Decimal("0"))])
    validity_days = models.PositiveSmallIntegerField(
        default=1, validators=[MinValueValidator(1), MaxValueValidator(14)],
        help_text="All places must be visited within this many days from the first visit date",
    )
    is_active = models.BooleanField(default=True)
    featured = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-featured", "name"]
        verbose_name = "combo pass"
        verbose_name_plural = "combo passes"

    def save(self, *args, **kwargs):
        if not self.slug:
            base = slugify(self.name)[:130] or "pass"
            slug, n = base, 2
            while ComboPass.objects.filter(slug=slug).exclude(pk=self.pk).exists():
                slug, n = f"{base}-{n}", n + 1
            self.slug = slug
        super().save(*args, **kwargs)

    def price_for(self, category):
        return getattr(self, f"price_{category}")

    @property
    def prices(self):
        return {c: self.price_for(c) for c in CATEGORIES}

    @property
    def from_price(self):
        """Lowest non-zero price ("from ₹..."), or 0 if everything is free."""
        paid = [p for p in self.prices.values() if p > 0]
        return min(paid) if paid else Decimal(0)

    def ordered_sites(self):
        return [s.museum for s in self.sites.select_related("museum__city__state").order_by("sort_order", "id")]

    def __str__(self):
        return self.name


class ComboPassSite(models.Model):
    combo_pass = models.ForeignKey(ComboPass, on_delete=models.CASCADE, related_name="sites")
    museum = models.ForeignKey(Museum, on_delete=models.PROTECT, related_name="pass_sites")
    sort_order = models.PositiveSmallIntegerField(default=0)

    class Meta:
        ordering = ["sort_order", "id"]
        unique_together = ("combo_pass", "museum")

    def __str__(self):
        return f"{self.combo_pass.name}: {self.museum.name}"


class PassOrder(models.Model):
    class Status(models.TextChoices):
        PENDING = "pending", "Pending payment"
        CONFIRMED = "confirmed", "Confirmed"
        CANCELLED = "cancelled", "Cancelled"
        EXPIRED = "expired", "Expired"

    class RefundStatus(models.TextChoices):
        NONE = "", "No refund"
        PENDING = "pending", "Refund initiated"
        PROCESSED = "processed", "Refunded"
        FAILED = "failed", "Refund failed"

    reference = models.CharField(max_length=12, unique=True, default=generate_pass_reference, editable=False)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="pass_orders")
    combo_pass = models.ForeignKey(ComboPass, on_delete=models.PROTECT, related_name="orders")
    pass_name = models.CharField(max_length=120)  # snapshot
    validity_days = models.PositiveSmallIntegerField()  # snapshot: later edits don't change bought passes
    start_date = models.DateField(db_index=True)
    indian_count = models.PositiveSmallIntegerField(default=0)
    foreign_count = models.PositiveSmallIntegerField(default=0)
    student_count = models.PositiveSmallIntegerField(default=0)
    child_count = models.PositiveSmallIntegerField(default=0)
    unit_prices = models.JSONField(default=dict, help_text="Price per category at the time of purchase")
    total_visitors = models.PositiveIntegerField()
    total_amount = models.DecimalField(max_digits=10, decimal_places=2)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.PENDING, db_index=True)
    visitor_name = models.CharField(max_length=120)
    visitor_email = models.EmailField(blank=True)
    visitor_phone = models.CharField(max_length=15, blank=True)
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
        return self.reference

    def count_for(self, category):
        return getattr(self, f"{category}_count")

    @property
    def end_date(self):
        return self.start_date + timedelta(days=self.validity_days - 1)

    @property
    def hold_expires_at(self):
        if self.status != self.Status.PENDING:
            return None
        return self.created_at + timedelta(minutes=settings.BOOKING_HOLD_MINUTES)

    @property
    def is_hold_expired(self):
        expires = self.hold_expires_at
        return expires is not None and timezone.now() >= expires

    @property
    def is_used(self):
        return self.visits.exists()

    @property
    def starts_at(self):
        return timezone.make_aware(datetime.combine(self.start_date, datetime.min.time()))

    @property
    def refundable_amount(self):
        """Full refund while the pass is unused and at least REFUND_FULL_BEFORE_HOURS before start_date."""
        if self.status != self.Status.CONFIRMED or not self.paid_at or self.total_amount <= 0 or self.is_used:
            return Decimal(0)
        hours_left = (self.starts_at - timezone.now()).total_seconds() / 3600
        return self.total_amount if hours_left >= settings.REFUND_FULL_BEFORE_HOURS else Decimal(0)

    @property
    def can_cancel(self):
        if self.status == self.Status.PENDING:
            return True
        return self.status == self.Status.CONFIRMED and not self.is_used and self.end_date >= timezone.localdate()


class PassVisit(models.Model):
    """The party entering one place of the pass (once per place)."""

    order = models.ForeignKey(PassOrder, on_delete=models.CASCADE, related_name="visits")
    museum = models.ForeignKey(Museum, on_delete=models.PROTECT, related_name="pass_visits")
    visited_at = models.DateTimeField()
    admitted = models.PositiveIntegerField()
    scanned_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+")
    scan_id = models.CharField(max_length=40, unique=True, null=True, blank=True, help_text="Client id: makes offline re-syncs safe")
    offline = models.BooleanField(default=False)
    gate = models.ForeignKey("museums.Gate", on_delete=models.SET_NULL, null=True, blank=True, related_name="pass_visits")

    class Meta:
        ordering = ["visited_at"]
        unique_together = ("order", "museum")

    def __str__(self):
        return f"{self.order.reference} @ {self.museum.name}"
