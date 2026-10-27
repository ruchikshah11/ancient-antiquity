import secrets
from datetime import timedelta

from django.conf import settings
from django.db import models
from django.utils import timezone

from museums.models import Museum, TicketType, TimeSlot


def generate_reference():
    # e.g. AA-7K2Q9M4X (no 0/O/1/I to avoid misreading at the gate)
    alphabet = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
    return "AA-" + "".join(secrets.choice(alphabet) for _ in range(8))


class Booking(models.Model):
    class Status(models.TextChoices):
        PENDING = "pending", "Pending payment"
        CONFIRMED = "confirmed", "Confirmed"
        CHECKED_IN = "checked_in", "Checked in"
        CANCELLED = "cancelled", "Cancelled"
        EXPIRED = "expired", "Expired"

    class PaymentMethod(models.TextChoices):
        UPI = "upi", "UPI"
        CARD = "card", "Card"
        NETBANKING = "netbanking", "Net banking"
        CASH = "cash", "Cash"
        WALLET = "wallet", "Wallet"
        FREE = "free", "Free entry"
        BANK_TRANSFER = "bank_transfer", "Bank transfer / invoice"
        ON_ACCOUNT = "on_account", "On account (tour operator credit)"

    class RefundStatus(models.TextChoices):
        NONE = "", "No refund"
        PENDING = "pending", "Refund initiated"
        PROCESSED = "processed", "Refunded"
        FAILED = "failed", "Refund failed"

    class Channel(models.TextChoices):
        ONLINE = "online", "Online"
        COUNTER = "counter", "Ticket counter"
        AGENT = "agent", "Tour operator"
        KIOSK = "kiosk", "Self-service kiosk"

    class GroupType(models.TextChoices):
        SCHOOL = "school", "School"
        COLLEGE = "college", "College / university"
        TOUR = "tour_operator", "Tour operator"
        CORPORATE = "corporate", "Company / corporate"
        NGO = "ngo", "NGO / community group"
        OTHER = "other", "Other group"

    EDUCATIONAL = (GroupType.SCHOOL, GroupType.COLLEGE)

    reference = models.CharField(max_length=12, unique=True, default=generate_reference, editable=False)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="bookings")
    museum = models.ForeignKey(Museum, on_delete=models.PROTECT, related_name="bookings")
    slot = models.ForeignKey(
        TimeSlot, on_delete=models.PROTECT, null=True, blank=True, related_name="bookings",
        help_text="Entry slot (empty for event tickets, which use event_session instead)",
    )
    event_session = models.ForeignKey(
        "events.EventSession", on_delete=models.PROTECT, null=True, blank=True, related_name="bookings",
        help_text="Event/show session for event tickets (events app)",
    )
    visit_date = models.DateField(db_index=True)
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.PENDING, db_index=True)
    channel = models.CharField(max_length=10, choices=Channel.choices, default=Channel.ONLINE, db_index=True)
    sold_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+",
        help_text="Staff member who sold a counter ticket",
    )
    agent = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True, blank=True, related_name="agent_bookings",
        help_text="Tour operator who booked on account (partners app)",
    )
    commission_amount = models.DecimalField(
        max_digits=10, decimal_places=2, default=0, help_text="Tour operator commission, deducted on their statement"
    )
    total_visitors = models.PositiveIntegerField(help_text="Everyone entering, including free escorts")
    total_amount = models.DecimalField(max_digits=10, decimal_places=2)
    discount_amount = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    promo_code = models.ForeignKey(
        "promotions.PromoCode", on_delete=models.SET_NULL, null=True, blank=True, related_name="bookings"
    )
    promo_discount = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    voucher_amount = models.DecimalField(
        max_digits=10, decimal_places=2, default=0, help_text="Part of the price paid with a gift voucher"
    )
    addons_amount = models.DecimalField(
        max_digits=10, decimal_places=2, default=0, help_text="Add-ons chosen at checkout (audio guide, camera...)"
    )
    membership = models.ForeignKey(
        "memberships.Membership", on_delete=models.SET_NULL, null=True, blank=True, related_name="bookings",
        help_text="Heritage Card whose discount was applied",
    )
    membership_discount = models.DecimalField(
        max_digits=10, decimal_places=2, default=0, help_text="Heritage Card discount on the entry tickets"
    )
    is_group = models.BooleanField(default=False, db_index=True)
    group_type = models.CharField(max_length=15, choices=GroupType.choices, blank=True)
    organisation_name = models.CharField(max_length=150, blank=True)
    escort_count = models.PositiveSmallIntegerField(default=0, help_text="Free escorts (teachers) included in total_visitors")
    visitors_arrived = models.PositiveIntegerField(default=0, help_text="How many have entered so far")
    gateway = models.CharField(max_length=12, blank=True, help_text="razorpay or mock")
    gateway_order_id = models.CharField(max_length=40, blank=True, db_index=True)
    refund_id = models.CharField(max_length=40, blank=True)
    refund_amount = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    refund_status = models.CharField(max_length=10, choices=RefundStatus.choices, blank=True, default="")
    visitor_name = models.CharField(max_length=120)
    visitor_email = models.EmailField(blank=True)
    visitor_phone = models.CharField(max_length=15, blank=True)
    payment_method = models.CharField(max_length=15, choices=PaymentMethod.choices, blank=True)
    payment_id = models.CharField(max_length=40, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    paid_at = models.DateTimeField(null=True, blank=True)
    cancelled_at = models.DateTimeField(null=True, blank=True)
    checked_in_at = models.DateTimeField(null=True, blank=True)
    checked_in_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    pay_by = models.DateTimeField(
        null=True, blank=True, help_text="Approved large-group bookings hold their seats until this time instead of the short hold"
    )
    group_request = models.ForeignKey(
        "grouprequests.GroupRequest", on_delete=models.SET_NULL, null=True, blank=True, related_name="bookings"
    )

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["museum", "visit_date", "slot"]),
            # Admin lists, reports and the dashboard: newest first, by status, by place, by visitor.
            models.Index(fields=["-created_at"], name="booking_created_idx"),
            models.Index(fields=["status", "created_at"], name="booking_status_created_idx"),
            models.Index(fields=["status", "visit_date"], name="booking_status_visit_idx"),
            models.Index(fields=["museum", "status", "created_at"], name="booking_museum_status_idx"),
            models.Index(fields=["user", "-created_at"], name="booking_user_created_idx"),
            # Settlements and payouts: paid bookings per place per period.
            models.Index(fields=["museum", "paid_at"], name="booking_museum_paid_idx"),
            # Covering index: dashboard revenue/visitor sums read it without touching the table.
            models.Index(fields=["status", "museum", "channel", "total_amount", "total_visitors"], name="booking_totals_idx"),
        ]

    def __str__(self):
        return self.reference

    @property
    def hold_expires_at(self):
        if self.status != self.Status.PENDING:
            return None
        if self.pay_by:
            return self.pay_by
        return self.created_at + timedelta(minutes=settings.BOOKING_HOLD_MINUTES)

    @property
    def is_hold_expired(self):
        expires = self.hold_expires_at
        return expires is not None and timezone.now() >= expires

    @property
    def tickets_amount(self):
        """Entry tickets before any discount (add-ons excluded)."""
        return (
            self.total_amount + self.discount_amount + self.membership_discount + self.promo_discount
            + self.voucher_amount - self.addons_amount
        )

    @property
    def addons_summary(self):
        """"2 x Audio guide, 1 x Camera permit" for the gate and the ticket ("" when none)."""
        return ", ".join(f"{a.quantity} x {a.name}" for a in self.addons.all())

    @property
    def remaining_to_enter(self):
        return max(self.total_visitors - self.visitors_arrived, 0)

    @property
    def is_event(self):
        return self.event_session_id is not None

    @property
    def slot_start_time(self):
        """Start time of the entry slot, or of the event session for event tickets."""
        if self.event_session_id:
            return self.event_session.start_time
        return self.slot.start_time if self.slot_id else None

    @property
    def slot_end_time(self):
        if self.event_session_id:
            return self.event_session.end_time
        return self.slot.end_time if self.slot_id else None

    @property
    def event_title(self):
        return self.event_session.event.title if self.event_session_id else ""

    @property
    def slot_starts_at(self):
        from datetime import datetime, time

        return timezone.make_aware(datetime.combine(self.visit_date, self.slot_start_time or time(0, 0)))

    @property
    def refundable_amount(self):
        """What a cancellation right now would refund under the policy (0 for unpaid/free bookings)."""
        if self.status != self.Status.CONFIRMED or not self.paid_at or self.total_amount <= 0:
            return 0
        if self.channel == self.Channel.COUNTER:
            return 0  # paid in cash/at the counter: refunded at the counter, not online
        hours_left = (self.slot_starts_at - timezone.now()).total_seconds() / 3600
        return self.total_amount if hours_left >= settings.REFUND_FULL_BEFORE_HOURS else 0

    @property
    def can_cancel(self):
        return self.status in (self.Status.PENDING, self.Status.CONFIRMED) and self.visit_date >= timezone.localdate()


class GateScan(models.Model):
    """One admission event at the gate. Groups can arrive in parts (e.g. 38 of 40, then 2 latecomers)."""

    booking = models.ForeignKey(Booking, on_delete=models.CASCADE, related_name="scans")
    admitted = models.PositiveIntegerField()
    scanned_at = models.DateTimeField()
    scanned_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+")
    scan_id = models.CharField(max_length=40, unique=True, null=True, blank=True, help_text="Client id: makes offline re-syncs safe")
    offline = models.BooleanField(default=False)
    gate = models.ForeignKey(
        "museums.Gate", on_delete=models.SET_NULL, null=True, blank=True, related_name="scans",
        help_text="Gate that admitted this scan (empty = not recorded)",
    )

    class Meta:
        ordering = ["scanned_at"]
        indexes = [models.Index(fields=["scanned_at"], name="gatescan_scanned_idx")]

    def __str__(self):
        return f"{self.booking.reference} +{self.admitted}"


class BookingItem(models.Model):
    booking = models.ForeignKey(Booking, on_delete=models.CASCADE, related_name="items")
    ticket_type = models.ForeignKey(
        TicketType, on_delete=models.PROTECT, null=True, blank=True, related_name="booking_items"
    )
    event_price = models.ForeignKey(
        "events.EventPrice", on_delete=models.SET_NULL, null=True, blank=True, related_name="booking_items",
        help_text="Event ticket category (event bookings; ticket_type is then empty)",
    )
    ticket_name = models.CharField(max_length=60)  # snapshot, survives later renames
    quantity = models.PositiveIntegerField()
    unit_price = models.DecimalField(max_digits=8, decimal_places=2)

    @property
    def line_total(self):
        return self.unit_price * self.quantity

    def __str__(self):
        return f"{self.booking.reference} {self.quantity} x {self.ticket_name}"


class BookingAddOn(models.Model):
    """An add-on chosen for a booking, with the name and price as they were when it was chosen."""

    booking = models.ForeignKey(Booking, on_delete=models.CASCADE, related_name="addons")
    addon = models.ForeignKey("addons.AddOn", on_delete=models.PROTECT, related_name="booking_lines")
    name = models.CharField(max_length=80)  # snapshot
    kind = models.CharField(max_length=12, blank=True)  # snapshot, for the icon
    quantity = models.PositiveIntegerField()
    unit_price = models.DecimalField(max_digits=8, decimal_places=2)

    class Meta:
        ordering = ["id"]

    @property
    def line_total(self):
        return self.unit_price * self.quantity

    def __str__(self):
        return f"{self.booking.reference} {self.quantity} x {self.name}"
