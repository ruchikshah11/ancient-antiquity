"""Combo pass purchase, payment, cancellation and gate admission."""
import secrets
from datetime import timedelta

from django.conf import settings
from django.db import transaction
from django.utils import timezone
from rest_framework.exceptions import ValidationError

from . import payments
from .models import CATEGORIES, PassOrder, PassVisit

MAX_PARTY = 20  # bigger parties book as a group at each place


def expire_stale_orders():
    cutoff = timezone.now() - timedelta(minutes=settings.BOOKING_HOLD_MINUTES)
    PassOrder.objects.filter(status=PassOrder.Status.PENDING, created_at__lt=cutoff).update(
        status=PassOrder.Status.EXPIRED
    )


def site_open_days(museum, start, end):
    """Days in start..end on which `museum` is open (weekly closed day and calendar closures excluded)."""
    day, out = start, []
    while day <= end:
        if not museum.is_closed_on(day) and not museum.closure_on(day)["closed"]:
            out.append(day)
        day += timedelta(days=1)
    return out


@transaction.atomic
def create_order(*, user, combo_pass, start_date, counts, visitor_name, visitor_email="", visitor_phone=""):
    """A pending order; free passes (all prices 0) are confirmed at once. `counts` = {category: n}."""
    if not combo_pass.is_active:
        raise ValidationError({"combo_pass": "This pass is not on sale."})
    today = timezone.localdate()
    if start_date < today:
        raise ValidationError({"start_date": "Choose today or a later date."})
    if start_date > today + timedelta(days=180):
        raise ValidationError({"start_date": "Passes can be bought up to 180 days ahead."})
    counts = {c: int(counts.get(c) or 0) for c in CATEGORIES}
    if any(n < 0 for n in counts.values()):
        raise ValidationError({"counts": "Visitor counts cannot be negative."})
    total_visitors = sum(counts.values())
    if total_visitors < 1:
        raise ValidationError({"counts": "Add at least one visitor."})
    if total_visitors > MAX_PARTY:
        raise ValidationError({"counts": f"A pass covers up to {MAX_PARTY} people. Larger parties can book as a group."})
    sites = combo_pass.ordered_sites()
    if not sites:
        raise ValidationError({"combo_pass": "This pass has no places."})
    end = start_date + timedelta(days=combo_pass.validity_days - 1)
    closed = [m.name for m in sites if not site_open_days(m, start_date, end)]
    if closed:
        raise ValidationError({"start_date": f"{', '.join(closed)} {'is' if len(closed) == 1 else 'are'} closed on "
                                             "the chosen date(s). Please pick another date."})
    unit_prices = {c: combo_pass.price_for(c) for c in CATEGORIES}
    total = sum(unit_prices[c] * counts[c] for c in CATEGORIES)
    order = PassOrder.objects.create(
        user=user,
        combo_pass=combo_pass,
        pass_name=combo_pass.name,
        validity_days=combo_pass.validity_days,
        start_date=start_date,
        unit_prices={c: str(p) for c, p in unit_prices.items()},
        total_visitors=total_visitors,
        total_amount=total,
        visitor_name=visitor_name,
        visitor_email=visitor_email,
        visitor_phone=visitor_phone,
        **{f"{c}_count": counts[c] for c in CATEGORIES},
    )
    if total == 0:
        confirm_payment(order, "free")
    return order


def confirm_payment(order, method, payment_id=None, gateway=None):
    order.status = PassOrder.Status.CONFIRMED
    order.payment_method = method
    if payment_id:
        order.payment_id = payment_id
    elif method == "free":
        order.payment_id = ""
    else:
        order.payment_id = "MOCK-" + secrets.token_hex(6).upper()
    order.gateway = gateway or ("" if method == "free" else payments.MOCK)
    order.paid_at = timezone.now()
    order.save(update_fields=["status", "payment_method", "payment_id", "paid_at", "gateway"])
    return order


class PaymentRefunded(ValidationError):
    """Raised after a payment for a cancelled order was refunded."""


def finalize_gateway_payment(order_id, payment_id, method):
    """Confirm a verified Razorpay payment. Safe to call twice. Passes hold no seats, so a late payment for a
    pending/expired order is still accepted; only a payment for a cancelled order is refunded."""
    order, refunded = _finalize(order_id, payment_id, method)
    if refunded:
        raise PaymentRefunded("This pass was already cancelled, so the payment has been refunded automatically.")
    return order


@transaction.atomic
def _finalize(order_id, payment_id, method):
    order = PassOrder.objects.select_for_update().get(pk=order_id)
    if order.status == PassOrder.Status.CONFIRMED:
        return order, False
    if order.payment_id == payment_id and order.refund_status:
        return order, True
    if order.status in (PassOrder.Status.PENDING, PassOrder.Status.EXPIRED) and order.end_date >= timezone.localdate():
        return confirm_payment(order, method, payment_id=payment_id, gateway=payments.RAZORPAY), False
    order.payment_id = payment_id
    order.gateway = payments.RAZORPAY
    if order.status != PassOrder.Status.CANCELLED:
        order.status = PassOrder.Status.EXPIRED
    order.save(update_fields=["payment_id", "gateway", "status"])
    issue_refund(order, order.total_amount)
    return order, True


def issue_refund(order, amount):
    if amount <= 0:
        return order
    order.refund_amount = amount
    if order.gateway == payments.RAZORPAY:
        refund = payments.refund(order, amount)
        order.refund_id = refund.get("id", "")
        order.refund_status = (
            PassOrder.RefundStatus.PROCESSED if refund.get("status") == "processed" else PassOrder.RefundStatus.PENDING
        )
    else:
        order.refund_id = "MOCKRF-" + secrets.token_hex(5).upper()
        order.refund_status = PassOrder.RefundStatus.PROCESSED
    order.save(update_fields=["refund_amount", "refund_id", "refund_status"])
    return order


@transaction.atomic
def cancel_order(order):
    """Cancel; full refund if unused and at least REFUND_FULL_BEFORE_HOURS before start_date, else none."""
    order = PassOrder.objects.select_for_update().get(pk=order.pk)
    if not order.can_cancel:
        raise ValidationError("This pass can no longer be cancelled.")
    refundable = order.refundable_amount
    order.status = PassOrder.Status.CANCELLED
    order.cancelled_at = timezone.now()
    order.save(update_fields=["status", "cancelled_at"])
    issue_refund(order, refundable)
    return order


# --- Gate admission ------------------------------------------------------------------------------------

def party_summary(order):
    labels = {"indian": "Indian", "foreign": "Foreign national", "student": "Student", "child": "Child"}
    return [{"quantity": order.count_for(c), "ticket_name": f"{labels[c]} (pass)"} for c in CATEGORIES if order.count_for(c)]


def admission_error(order, museum, day):
    """Why this pass cannot enter `museum` on `day` (None if it can). Ignores 'already used here'."""
    if order.status == PassOrder.Status.PENDING:
        return "This pass has not been paid."
    if order.status != PassOrder.Status.CONFIRMED:
        return f"This pass is {order.get_status_display().lower()}."
    if not order.combo_pass.sites.filter(museum=museum).exists():
        return f"{museum.name} is not included in the {order.pass_name}."
    if day < order.start_date:
        return f"This pass is valid from {order.start_date:%d %b %Y}."
    if day > order.end_date:
        return f"This pass was valid until {order.end_date:%d %b %Y}."
    return None


def admit(order, museum, user, *, at=None, scan_id=None, offline=False, gate=None):
    """Admit the whole party at `museum` (once). Returns (visit, created). Raises ValidationError when not valid.

    Must be called inside a transaction with `order` locked (select_for_update).
    """
    if scan_id:
        existing = PassVisit.objects.filter(scan_id=scan_id).first()
        if existing:
            return existing, False
    at = at or timezone.now()
    error = admission_error(order, museum, timezone.localdate(at))
    if error:
        raise ValidationError({"reference": error})
    used = order.visits.filter(museum=museum).first()
    if used:
        raise ValidationError({"reference": f"This pass was already used here at "
                                            f"{timezone.localtime(used.visited_at):%d %b %Y %H:%M}."})
    visit = PassVisit.objects.create(
        order=order, museum=museum, visited_at=at, admitted=order.total_visitors, scanned_by=user,
        scan_id=scan_id or None, offline=offline, gate=gate,
    )
    return visit, True


def lock_order(reference):
    return (
        PassOrder.objects.select_for_update()
        .select_related("combo_pass").filter(reference=reference.strip().upper()).first()
    )


def manifest_entries(museum, day):
    """Confirmed passes valid at `museum` on `day`, shaped like gate-manifest tickets (for offline checking)."""
    orders = (
        PassOrder.objects.filter(
            status=PassOrder.Status.CONFIRMED, combo_pass__sites__museum=museum, start_date__lte=day,
            start_date__gte=day - timedelta(days=14),
        )
        .prefetch_related("visits")
        .order_by("reference")
        .distinct()
    )
    out = []
    for order in orders:
        if order.end_date < day:
            continue
        visit = next((v for v in order.visits.all() if v.museum_id == museum.id), None)
        out.append({
            "reference": order.reference,
            "status": "checked_in" if visit else "confirmed",
            "visitor_name": order.visitor_name,
            "total_visitors": order.total_visitors,
            "slot_start": museum.opening_time,
            "slot_end": museum.closing_time,
            "items": ", ".join(f"{i['quantity']} x {i['ticket_name']}" for i in party_summary(order)),
            "checked_in_at": visit.visited_at if visit else None,
            "is_group": False,
            "organisation_name": "",
            "visitors_arrived": order.total_visitors if visit else 0,
            "is_pass": True,
            "pass_name": order.pass_name,
            "valid_until": order.end_date,
        })
    return out


def checkin_payload(order, museum):
    """What the gate screen shows after admitting a pass."""
    sites = order.combo_pass.ordered_sites()
    used = set(order.visits.values_list("museum_id", flat=True))
    return {
        "kind": "pass",
        "reference": order.reference,
        "pass_name": order.pass_name,
        "visitor_name": order.visitor_name,
        "total_visitors": order.total_visitors,
        "items": party_summary(order),
        "museum_name": museum.name,
        "valid_from": order.start_date,
        "valid_until": order.end_date,
        "sites_total": len(sites),
        "sites_used": len([m for m in sites if m.id in used]),
    }
