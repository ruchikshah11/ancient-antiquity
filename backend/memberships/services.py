"""Heritage Card purchase, payment, cancellation and the booking benefit."""
import secrets
from datetime import timedelta
from decimal import ROUND_HALF_UP, Decimal

from django.conf import settings
from django.db import transaction
from django.db.models import Max
from django.utils import timezone
from rest_framework.exceptions import ValidationError

from . import payments
from .models import Membership

ZERO = Decimal("0")


def expire_stale():
    """Unpaid purchases past the hold and cards past their last day become expired."""
    cutoff = timezone.now() - timedelta(minutes=settings.BOOKING_HOLD_MINUTES)
    Membership.objects.filter(status=Membership.Status.PENDING, created_at__lt=cutoff).update(
        status=Membership.Status.EXPIRED
    )
    Membership.objects.filter(status=Membership.Status.ACTIVE, ends_on__lt=timezone.localdate()).update(
        status=Membership.Status.EXPIRED
    )


def current_for(user, day=None):
    """The user's card valid on `day` (default today), or None. Prefers the best benefit if several overlap."""
    if not user or not user.is_authenticated:
        return None
    day = day or timezone.localdate()
    cards = Membership.objects.filter(
        user=user, status=Membership.Status.ACTIVE, starts_on__lte=day, ends_on__gte=day
    ).select_related("plan")
    return max(cards, key=lambda m: (m.benefit_percent, m.max_visitors_per_booking), default=None)


def valid_at(membership, museum):
    places = membership.plan.places
    return not places.exists() or places.filter(pk=museum.pk).exists()


def booking_benefit(user, museum, visit_date, units):
    """Heritage Card discount for an online booking. Returns (membership, discount) or (None, 0).

    `units` = [(unit_price, quantity), ...]. The plan's percentage (100 for free entry) is taken off up to
    max_visitors_per_booking tickets, the most expensive first, rounded to whole rupees like group discounts.
    """
    if not user or not user.is_authenticated:
        return None, ZERO
    day_cards = Membership.objects.filter(
        user=user, status=Membership.Status.ACTIVE, starts_on__lte=visit_date, ends_on__gte=visit_date
    ).select_related("plan")
    best, best_discount = None, ZERO
    prices = sorted((Decimal(p) for p, q in units for _ in range(q)), reverse=True)
    for card in day_cards:
        if not valid_at(card, museum):
            continue
        covered = sum(prices[: card.max_visitors_per_booking], ZERO)
        discount = (covered * card.benefit_percent / Decimal(100)).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
        if discount > best_discount:
            best, best_discount = card, discount
    return best, best_discount


@transaction.atomic
def create_membership(*, user, plan, holder_name=""):
    """A pending card; free plans are activated at once."""
    if not plan.is_active:
        raise ValidationError({"plan": "This plan is not on sale."})
    name = (holder_name or "").strip() or f"{user.first_name} {user.last_name}".strip() or user.email
    membership = Membership.objects.create(
        user=user,
        plan=plan,
        plan_name=plan.name,
        discount_percent=plan.discount_percent,
        free_entry=plan.free_entry,
        max_visitors_per_booking=plan.max_visitors_per_booking,
        duration_days=plan.duration_days,
        holder_name=name[:120],
        total_amount=plan.price,
    )
    if plan.price == 0:
        confirm_payment(membership, "free")
    return membership


def _start_date(membership):
    """Today, or the day after the member's current card ends (renewing early adds the year on top)."""
    today = timezone.localdate()
    last = (
        Membership.objects.filter(user=membership.user, status=Membership.Status.ACTIVE, ends_on__gte=today)
        .exclude(pk=membership.pk).aggregate(m=Max("ends_on"))["m"]
    )
    return last + timedelta(days=1) if last else today


def confirm_payment(membership, method, payment_id=None, gateway=None):
    membership.status = Membership.Status.ACTIVE
    membership.payment_method = method
    if payment_id:
        membership.payment_id = payment_id
    elif method == "free":
        membership.payment_id = ""
    else:
        membership.payment_id = "MOCK-" + secrets.token_hex(6).upper()
    membership.gateway = gateway or ("" if method == "free" else payments.MOCK)
    membership.paid_at = timezone.now()
    membership.starts_on = _start_date(membership)
    membership.ends_on = membership.starts_on + timedelta(days=membership.duration_days - 1)
    membership.save(update_fields=["status", "payment_method", "payment_id", "paid_at", "gateway", "starts_on", "ends_on"])
    return membership


class PaymentRefunded(ValidationError):
    """Raised after a payment for a cancelled membership was refunded."""


def finalize_gateway_payment(order_id, payment_id, method="upi"):
    """Confirm a verified Razorpay payment for Membership `order_id` (pk). Safe to call twice (checkout + webhook).

    Cards hold no seats, so a late payment for a pending/expired purchase is still accepted; only a payment for a
    cancelled one is refunded (PaymentRefunded is raised after the refund has been saved).
    """
    membership, refunded = _finalize(order_id, payment_id, method)
    if refunded:
        raise PaymentRefunded("This membership was already cancelled, so the payment has been refunded automatically.")
    return membership


@transaction.atomic
def _finalize(order_id, payment_id, method):
    membership = Membership.objects.select_for_update().get(pk=order_id)
    if membership.status == Membership.Status.ACTIVE or (membership.paid_at and membership.status == Membership.Status.EXPIRED):
        return membership, False  # already handled
    if membership.payment_id == payment_id and membership.refund_status:
        return membership, True
    if membership.status in (Membership.Status.PENDING, Membership.Status.EXPIRED):
        return confirm_payment(membership, method, payment_id=payment_id, gateway=payments.RAZORPAY), False
    membership.payment_id = payment_id
    membership.gateway = payments.RAZORPAY
    membership.save(update_fields=["payment_id", "gateway"])
    issue_refund(membership, membership.total_amount)
    return membership, True


def issue_refund(membership, amount):
    if amount <= 0:
        return membership
    membership.refund_amount = amount
    if membership.gateway == payments.RAZORPAY:
        refund = payments.refund(membership, amount)
        membership.refund_id = refund.get("id", "")
        membership.refund_status = (
            Membership.RefundStatus.PROCESSED if refund.get("status") == "processed" else Membership.RefundStatus.PENDING
        )
    else:
        membership.refund_id = "MOCKRF-" + secrets.token_hex(5).upper()
        membership.refund_status = Membership.RefundStatus.PROCESSED
    membership.save(update_fields=["refund_amount", "refund_id", "refund_status"])
    return membership


@transaction.atomic
def cancel_membership(membership, refund=False):
    """Admin cancel. With refund=True the full price goes back to the original payment (free/demo: at once)."""
    membership = Membership.objects.select_for_update().get(pk=membership.pk)
    if membership.status == Membership.Status.CANCELLED:
        raise ValidationError("This membership is already cancelled.")
    was_paid = membership.paid_at is not None
    membership.status = Membership.Status.CANCELLED
    membership.cancelled_at = timezone.now()
    membership.save(update_fields=["status", "cancelled_at"])
    if refund and was_paid:
        issue_refund(membership, membership.total_amount)
    return membership

