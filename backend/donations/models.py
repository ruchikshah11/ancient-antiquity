"""Donations to the heritage fund (or to one place), with 80G receipts.

A donation is created pending, paid through the same gateway as bookings (Razorpay or the demo gateway), and
gets a financial-year receipt number (e.g. AAHF/2026-27/000123) only once it is paid.
"""
import re
import secrets
from decimal import Decimal

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import MinValueValidator
from django.db import models

MIN_AMOUNT = Decimal("100")
MAX_AMOUNT = Decimal("10000000")  # 1 crore: larger gifts are arranged with the trust directly
PRESET_AMOUNTS = (500, 1000, 2500, 5000)
PAN_RE = re.compile(r"^[A-Z]{5}[0-9]{4}[A-Z]$")


def validate_pan(value):
    if value and not PAN_RE.match(value):
        raise ValidationError("Enter a valid PAN, e.g. ABCDE1234F.")


def generate_donation_reference():
    alphabet = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
    return "AD-" + "".join(secrets.choice(alphabet) for _ in range(8))


def financial_year(day):
    """Indian financial year (April-March) of a date, e.g. 2026-27."""
    start = day.year if day.month >= 4 else day.year - 1
    return f"{start}-{(start + 1) % 100:02d}"


def receipt_prefix():
    """Initials of the trust name (Ancient Antiquity Heritage Foundation -> AAHF)."""
    skip = {"of", "the", "and", "for", "&"}
    words = [w for w in re.split(r"[\s\-]+", settings.DONATION_TRUST_NAME or "") if w and w.lower() not in skip]
    initials = "".join(w[0] for w in words if w[0].isalpha()).upper()
    return initials[:8] or "AAHF"


class Donation(models.Model):
    class Status(models.TextChoices):
        PENDING = "pending", "Pending payment"
        PAID = "paid", "Paid"
        FAILED = "failed", "Payment failed"
        REFUNDED = "refunded", "Refunded"

    reference = models.CharField(max_length=12, unique=True, default=generate_donation_reference, editable=False)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="donations"
    )
    museum = models.ForeignKey(
        "museums.Museum", on_delete=models.PROTECT, null=True, blank=True, related_name="donations",
        help_text="Where the gift should go; empty = the general heritage fund",
    )
    donor_name = models.CharField(max_length=120)
    donor_email = models.EmailField()
    donor_phone = models.CharField(max_length=15, blank=True)
    donor_pan = models.CharField(max_length=10, blank=True, validators=[validate_pan],
                                 help_text="Needed for an 80G deduction")
    donor_address = models.CharField(max_length=300, blank=True, help_text="Needed for an 80G receipt")
    amount = models.DecimalField(max_digits=11, decimal_places=2, validators=[MinValueValidator(MIN_AMOUNT)])
    wants_80g = models.BooleanField(default=False)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.PENDING, db_index=True)
    receipt_number = models.CharField(max_length=40, unique=True, null=True, blank=True, editable=False)
    receipt_fy = models.CharField(max_length=7, blank=True, editable=False)
    receipt_seq = models.PositiveIntegerField(null=True, blank=True, editable=False)
    payment_method = models.CharField(max_length=15, blank=True, help_text="Same values as Booking.payment_method")
    payment_id = models.CharField(max_length=40, blank=True)
    gateway = models.CharField(max_length=12, blank=True, help_text="razorpay or mock")
    gateway_order_id = models.CharField(max_length=40, blank=True, db_index=True)
    refund_id = models.CharField(max_length=40, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    paid_at = models.DateTimeField(null=True, blank=True, db_index=True)
    refunded_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]
        constraints = [
            models.UniqueConstraint(fields=["receipt_fy", "receipt_seq"], name="donation_unique_fy_seq"),
        ]

    def __str__(self):
        return self.receipt_number or self.reference

    @property
    def purpose(self):
        return self.museum.name if self.museum_id else "General heritage fund"

    @property
    def is_80g_eligible(self):
        """The 80G wording is printed only when asked for and a PAN was given."""
        return bool(self.wants_80g and self.donor_pan)


class ReceiptCounter(models.Model):
    """Last receipt number used in a financial year. Locked row = gap-free, collision-free numbering."""

    financial_year = models.CharField(max_length=7, unique=True)
    last_number = models.PositiveIntegerField(default=0)

    def __str__(self):
        return f"{self.financial_year}: {self.last_number}"
