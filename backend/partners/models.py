"""Partners: tour operators who book on credit, museum (partner) settlements and self-service kiosks."""
from decimal import Decimal

from django.conf import settings
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models

DEFAULT_COMMISSION_PERCENT = Decimal("5")
DEFAULT_PLATFORM_FEE_PERCENT = Decimal("5")
GST_ON_FEE_PERCENT = Decimal("18")


class AgentProfile(models.Model):
    """A tour operator / travel agent. Applies as a visitor; an administrator approves (role becomes agent)."""

    class Status(models.TextChoices):
        PENDING = "pending", "Pending review"
        APPROVED = "approved", "Approved"
        REJECTED = "rejected", "Rejected"
        SUSPENDED = "suspended", "Suspended"

    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="agent_profile")
    company_name = models.CharField(max_length=150)
    gstin = models.CharField(max_length=15, blank=True, help_text="15-character GST number (optional)")
    contact_phone = models.CharField(max_length=15)
    city = models.CharField(max_length=80, blank=True)
    message = models.TextField(blank=True, help_text="What the applicant told us about their business")
    commission_percent = models.DecimalField(
        max_digits=5, decimal_places=2, default=DEFAULT_COMMISSION_PERCENT,
        validators=[MinValueValidator(Decimal("0")), MaxValueValidator(Decimal("50"))],
    )
    credit_limit = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    balance = models.DecimalField(
        max_digits=12, decimal_places=2, default=0,
        help_text="Amount owed: net (after commission) of live on-account bookings minus payments received",
    )
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.PENDING, db_index=True)
    is_approved = models.BooleanField(default=False)
    approved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    approved_at = models.DateTimeField(null=True, blank=True)
    admin_note = models.CharField(max_length=255, blank=True, help_text="Reason for rejection, internal notes")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("-created_at",)

    def __str__(self):
        return f"{self.company_name} ({self.user.email})"

    @property
    def credit_available(self):
        return max(self.credit_limit - self.balance, Decimal(0))


class AgentPayment(models.Model):
    """Money received from a tour operator (bank transfer, cheque...). Reduces their balance."""

    agent = models.ForeignKey(AgentProfile, on_delete=models.PROTECT, related_name="payments")
    amount = models.DecimalField(max_digits=12, decimal_places=2, validators=[MinValueValidator(Decimal("0.01"))])
    reference = models.CharField(max_length=80, help_text="UTR / cheque number / receipt")
    note = models.CharField(max_length=255, blank=True)
    received_on = models.DateField()
    recorded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("-received_on", "-created_at")

    def __str__(self):
        return f"{self.agent.company_name}: {self.amount} ({self.reference})"


class PartnerAccount(models.Model):
    """Payout details of a place (the partner). Bank account numbers are only ever shown masked."""

    museum = models.OneToOneField("museums.Museum", on_delete=models.CASCADE, related_name="partner_account")
    account_holder = models.CharField(max_length=150, blank=True)
    bank_name = models.CharField(max_length=100, blank=True)
    account_number = models.CharField(max_length=30, blank=True, help_text="Write-only through the API")
    ifsc = models.CharField(max_length=11, blank=True)
    razorpay_account_id = models.CharField(
        max_length=40, blank=True, help_text="Linked account id (acc_...) for Razorpay Route transfers"
    )
    platform_fee_percent = models.DecimalField(
        max_digits=5, decimal_places=2, default=DEFAULT_PLATFORM_FEE_PERCENT,
        validators=[MinValueValidator(Decimal("0")), MaxValueValidator(Decimal("50"))],
    )
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"Payout account of {self.museum}"

    @property
    def masked_account_number(self):
        n = self.account_number.strip()
        return f"XXXX{n[-4:]}" if n else ""


class Settlement(models.Model):
    """What the platform owes a place for a period (or the place owes, when counter cash exceeds payouts)."""

    class Status(models.TextChoices):
        DRAFT = "draft", "Draft"
        APPROVED = "approved", "Approved"
        PAID = "paid", "Paid"

    museum = models.ForeignKey("museums.Museum", on_delete=models.PROTECT, related_name="settlements")
    period_start = models.DateField()
    period_end = models.DateField()
    booking_count = models.PositiveIntegerField(default=0)
    visitor_count = models.PositiveIntegerField(default=0)
    gross_online = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    gross_kiosk = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    gross_counter = models.DecimalField(
        max_digits=12, decimal_places=2, default=0, help_text="Collected by the place itself at its counter"
    )
    gross_agent = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    refunds = models.DecimalField(
        max_digits=12, decimal_places=2, default=0,
        help_text="Refunds in this period for bookings paid in an earlier period",
    )
    platform_fee_percent = models.DecimalField(max_digits=5, decimal_places=2, default=DEFAULT_PLATFORM_FEE_PERCENT)
    platform_fee = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    gst_on_fee = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    net_payable = models.DecimalField(
        max_digits=12, decimal_places=2, default=0, help_text="Negative: the place owes the platform"
    )
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.DRAFT, db_index=True)
    approved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    approved_at = models.DateTimeField(null=True, blank=True)
    paid_reference = models.CharField(max_length=80, blank=True)
    paid_at = models.DateTimeField(null=True, blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("-period_end", "museum__name")
        constraints = [
            models.UniqueConstraint(fields=["museum", "period_start", "period_end"], name="unique_settlement_period"),
        ]

    def __str__(self):
        return f"{self.museum} {self.period_start}..{self.period_end}"

    @property
    def gross_total(self):
        return self.gross_online + self.gross_kiosk + self.gross_counter + self.gross_agent


class KioskDevice(models.Model):
    """An unattended self-service screen. Its user account (role kiosk) may only sell for these places."""

    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="kiosk_device")
    name = models.CharField(max_length=100, help_text="e.g. 'Red Fort gate 2 kiosk'")
    museums = models.ManyToManyField("museums.Museum", related_name="kiosks", blank=True)
    is_active = models.BooleanField(default=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("name",)

    def __str__(self):
        return self.name
