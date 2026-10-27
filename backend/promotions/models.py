import secrets
from datetime import timedelta

from django.conf import settings
from django.db import models
from django.db.models.functions import Upper
from django.utils import timezone

from museums.models import Museum


class PromoCode(models.Model):
    class DiscountType(models.TextChoices):
        PERCENT = "percent", "Percent"
        FLAT = "flat", "Flat amount"

    class Scope(models.TextChoices):
        ALL = "all", "All places"
        MUSEUMS = "museums", "Selected places"
        PLACE_TYPES = "place_types", "Place types"

    class AppliesTo(models.TextChoices):
        INDIVIDUAL = "individual", "Individual bookings"
        GROUP = "group", "Group bookings"
        BOTH = "both", "Both"

    code = models.CharField(max_length=30, help_text="Matched case-insensitively; stored upper-case")
    description = models.CharField(max_length=200, blank=True)
    discount_type = models.CharField(max_length=10, choices=DiscountType.choices, default=DiscountType.PERCENT)
    value = models.DecimalField(max_digits=10, decimal_places=2)
    max_discount = models.DecimalField(
        max_digits=10, decimal_places=2, null=True, blank=True, help_text="Cap for percent discounts"
    )
    min_order_amount = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    valid_from = models.DateTimeField(null=True, blank=True)
    valid_to = models.DateTimeField(null=True, blank=True)
    usage_limit = models.PositiveIntegerField(null=True, blank=True, help_text="Total uses (blank = unlimited)")
    per_user_limit = models.PositiveIntegerField(null=True, blank=True, default=1, help_text="Blank = unlimited")
    scope = models.CharField(max_length=12, choices=Scope.choices, default=Scope.ALL)
    museums = models.ManyToManyField(Museum, blank=True, related_name="promo_codes")
    place_types = models.CharField(max_length=100, blank=True, help_text="Comma-separated, e.g. fort,palace")
    applies_to = models.CharField(max_length=10, choices=AppliesTo.choices, default=AppliesTo.BOTH)
    first_booking_only = models.BooleanField(default=False)
    is_active = models.BooleanField(default=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        constraints = [models.UniqueConstraint(Upper("code"), name="promo_code_unique_ci")]

    def save(self, *args, **kwargs):
        self.code = (self.code or "").strip().upper()
        super().save(*args, **kwargs)

    def __str__(self):
        return self.code

    @property
    def place_type_list(self):
        return [t.strip() for t in self.place_types.split(",") if t.strip()]


class PromoRedemption(models.Model):
    code = models.ForeignKey(PromoCode, on_delete=models.CASCADE, related_name="redemptions")
    booking = models.ForeignKey("bookings.Booking", on_delete=models.CASCADE, related_name="promo_redemptions")
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="promo_redemptions")
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.code} on {self.booking}"


def generate_voucher_code():
    alphabet = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
    part = lambda: "".join(secrets.choice(alphabet) for _ in range(4))  # noqa: E731
    return f"GV-{part()}-{part()}"


def default_valid_until():
    return timezone.localdate() + timedelta(days=365)


class GiftVoucher(models.Model):
    code = models.CharField(max_length=14, unique=True, default=generate_voucher_code, editable=False)
    initial_value = models.DecimalField(max_digits=10, decimal_places=2)
    balance = models.DecimalField(max_digits=10, decimal_places=2)
    purchaser_name = models.CharField(max_length=120, blank=True)
    purchaser_email = models.EmailField(blank=True)
    recipient_name = models.CharField(max_length=120, blank=True)
    recipient_email = models.EmailField(blank=True)
    message = models.TextField(blank=True)
    valid_until = models.DateField(default=default_valid_until)
    is_active = models.BooleanField(default=True)
    issued_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return self.code

    @property
    def is_expired(self):
        return self.valid_until < timezone.localdate()


class VoucherRedemption(models.Model):
    voucher = models.ForeignKey(GiftVoucher, on_delete=models.CASCADE, related_name="redemptions")
    booking = models.ForeignKey("bookings.Booking", on_delete=models.CASCADE, related_name="voucher_redemptions")
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    created_at = models.DateTimeField(auto_now_add=True)
    reversed_at = models.DateTimeField(null=True, blank=True, help_text="Amount returned to the voucher balance")

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.voucher} -{self.amount} on {self.booking}"
