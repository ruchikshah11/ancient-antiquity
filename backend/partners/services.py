"""Business rules for tour operators (credit bookings), place settlements and kiosk sales."""
import datetime
import secrets
from decimal import ROUND_HALF_UP, Decimal

from django.conf import settings
from django.db import transaction
from django.db.models import Count, Q, Sum
from django.utils import timezone
from rest_framework.exceptions import ValidationError

from bookings import services as booking_services
from bookings.models import Booking
from museums.models import Museum
from ancient_antiquity.dates import day_range, day_start

from .models import (
    DEFAULT_PLATFORM_FEE_PERCENT, GST_ON_FEE_PERCENT, AgentPayment, AgentProfile, PartnerAccount, Settlement,
)

CENT = Decimal("0.01")
LIVE = (Booking.Status.CONFIRMED, Booking.Status.CHECKED_IN)


def money(value):
    return Decimal(value or 0).quantize(CENT, rounding=ROUND_HALF_UP)


# --------------------------------------------------------------------------------------- tour operators

def on_account_bookings(profile):
    return Booking.objects.filter(agent=profile.user, payment_method=Booking.PaymentMethod.ON_ACCOUNT)


def compute_balance(profile):
    """Net (gross minus commission) of live on-account bookings, minus every payment received."""
    owed = on_account_bookings(profile).filter(status__in=LIVE).aggregate(
        gross=Sum("total_amount"), commission=Sum("commission_amount")
    )
    paid = profile.payments.aggregate(n=Sum("amount"))["n"] or 0
    return money((owed["gross"] or 0) - (owed["commission"] or 0) - paid)


def recalc_balance(profile):
    """Recompute the stored balance from the ledger, so any booking change (cancel, admin edit) stays consistent."""
    balance = compute_balance(profile)
    if balance != profile.balance:
        AgentProfile.objects.filter(pk=profile.pk).update(balance=balance)
        profile.balance = balance
    return profile


def commission_for(total, percent):
    return money(Decimal(total) * Decimal(percent) / Decimal(100))


@transaction.atomic
def create_agent_booking(*, profile, data):
    """Book for a tour operator: confirmed at once and charged to their account when credit allows.

    `data` is validated BookingCreateSerializer / GroupBookingSerializer data.
    """
    profile = AgentProfile.objects.select_for_update().get(pk=profile.pk)
    if not profile.is_approved:
        raise ValidationError("Your tour operator account is not approved.")
    booking = booking_services.create_booking(user=profile.user, channel=Booking.Channel.AGENT, **data)
    commission = commission_for(booking.total_amount, profile.commission_percent)
    net = booking.total_amount - commission
    balance = compute_balance(profile)
    if net > 0 and balance + net > profile.credit_limit:
        available = max(profile.credit_limit - balance, Decimal(0))
        # Raising rolls back the booking created above (same transaction).
        raise ValidationError({
            "credit": f"Not enough credit: this booking needs {net:.2f} on account but only {available:.2f} is available. "
                      "Please pay your outstanding balance or ask us to raise your credit limit."
        })
    booking.agent = profile.user
    booking.commission_amount = commission
    booking.save(update_fields=["agent", "commission_amount"])
    if booking.status == Booking.Status.PENDING:
        booking_services.confirm_payment(
            booking, Booking.PaymentMethod.ON_ACCOUNT, payment_id="ACC-" + secrets.token_hex(5).upper(), gateway="account"
        )
    recalc_balance(profile)
    booking.refresh_from_db()
    return booking


def agent_can_cancel(booking):
    """Agents may cancel up to REFUND_FULL_BEFORE_HOURS (24h) before the slot; the amount leaves their balance."""
    if booking.status not in (Booking.Status.PENDING, Booking.Status.CONFIRMED):
        return False
    hours_left = (booking.slot_starts_at - timezone.now()).total_seconds() / 3600
    return hours_left >= settings.REFUND_FULL_BEFORE_HOURS


@transaction.atomic
def cancel_agent_booking(booking, profile):
    booking = Booking.objects.select_for_update(of=("self",)).select_related("slot", "event_session").get(pk=booking.pk)
    if not agent_can_cancel(booking):
        raise ValidationError(
            f"Bookings can be cancelled up to {settings.REFUND_FULL_BEFORE_HOURS} hours before the visit slot."
        )
    booking.status = Booking.Status.CANCELLED
    booking.cancelled_at = timezone.now()
    booking.save(update_fields=["status", "cancelled_at"])  # on account: nothing goes back through a gateway
    recalc_balance(profile)
    return booking


@transaction.atomic
def record_agent_payment(*, profile, amount, reference, note="", received_on=None, by=None):
    payment = AgentPayment.objects.create(
        agent=profile, amount=amount, reference=reference, note=note,
        received_on=received_on or timezone.localdate(), recorded_by=by,
    )
    recalc_balance(profile)
    return payment


def month_bounds(month):
    """'YYYY-MM' -> (first day, last day). Raises ValidationError on bad input."""
    try:
        year, mon = (int(x) for x in month.split("-"))
        first = datetime.date(year, mon, 1)
    except (ValueError, AttributeError):
        raise ValidationError({"month": "Use the format YYYY-MM."})
    nxt = datetime.date(year + (mon == 12), mon % 12 + 1, 1)
    return first, nxt - datetime.timedelta(days=1)


def agent_statement(profile, month):
    """Monthly statement: on-account bookings made in the month, commission, net payable and payments."""
    first, last = month_bounds(month)
    bookings = list(
        Booking.objects.filter(agent=profile.user, created_at__gte=day_start(first), created_at__lt=day_range(first, last)[1])
        .select_related("museum", "slot").prefetch_related("items").order_by("created_at")
    )
    live = [b for b in bookings if b.status in LIVE]
    gross = money(sum(b.total_amount for b in live))
    commission = money(sum(b.commission_amount for b in live))
    payments = list(profile.payments.filter(received_on__gte=first, received_on__lte=last).order_by("received_on"))
    received = money(sum(p.amount for p in payments))
    return {
        "month": f"{first:%Y-%m}",
        "from": first,
        "to": last,
        "company_name": profile.company_name,
        "gstin": profile.gstin,
        "commission_percent": profile.commission_percent,
        "bookings": bookings,
        "booking_count": len(live),
        "visitors": sum(b.total_visitors for b in live),
        "cancelled_count": sum(1 for b in bookings if b.status == Booking.Status.CANCELLED),
        "gross": gross,
        "commission": commission,
        "net_payable": money(gross - commission),
        "payments": payments,
        "payments_received": received,
        "outstanding_balance": profile.balance,
        "credit_limit": profile.credit_limit,
        "credit_available": profile.credit_available,
    }


def agent_dashboard(profile):
    today = timezone.localdate()
    first = today.replace(day=1)
    month = on_account_bookings(profile).filter(created_at__gte=day_start(first), status__in=LIVE).aggregate(
        bookings=Count("id"), visitors=Sum("total_visitors"), gross=Sum("total_amount"),
        commission=Sum("commission_amount"),
    )
    upcoming = Booking.objects.filter(agent=profile.user, status=Booking.Status.CONFIRMED, visit_date__gte=today).count()
    return {
        "credit_limit": profile.credit_limit,
        "credit_used": profile.balance,
        "credit_available": profile.credit_available,
        "upcoming_visits": upcoming,
        "this_month": {
            "bookings": month["bookings"] or 0,
            "visitors": month["visitors"] or 0,
            "gross": money(month["gross"]),
            "commission": money(month["commission"]),
            "net": money((month["gross"] or 0) - (month["commission"] or 0)),
        },
    }


# --------------------------------------------------------------------------------------- settlements

def fee_percent_for(museum):
    account = PartnerAccount.objects.filter(museum=museum).first()
    if account:
        return account.platform_fee_percent
    return Decimal(str(getattr(settings, "PARTNER_PLATFORM_FEE_PERCENT", DEFAULT_PLATFORM_FEE_PERCENT)))


def settlement_bookings(museum, start, end):
    """Paid bookings that count for a period: paid within it, still live and not refunded."""
    return (
        Booking.objects.filter(museum=museum, paid_at__gte=day_start(start), paid_at__lt=day_range(start, end)[1], status__in=LIVE)
        .filter(Q(refund_status="") | Q(refund_amount=0))
    )


def late_refunds(museum, start, end):
    """Refunds made in the period for bookings paid before it (already counted in an earlier settlement)."""
    return Booking.objects.filter(
        museum=museum, refund_amount__gt=0, cancelled_at__date__gte=start, cancelled_at__date__lte=end,
        paid_at__lt=day_start(start),
    )


def compute_settlement(museum, start, end):
    qs = settlement_bookings(museum, start, end)
    by_channel = {
        r["channel"]: r for r in qs.order_by().values("channel").annotate(
            amount=Sum("total_amount"), voucher=Sum("voucher_amount"), n=Count("id"), visitors=Sum("total_visitors"),
        )
    }

    def gross(channel):
        r = by_channel.get(channel, {})
        # Gift-voucher money was collected by the platform when the voucher was sold, so it counts too.
        return money((r.get("amount") or 0) + (r.get("voucher") or 0))

    values = {
        "gross_online": gross(Booking.Channel.ONLINE),
        "gross_kiosk": gross(Booking.Channel.KIOSK),
        "gross_counter": gross(Booking.Channel.COUNTER),
        "gross_agent": gross(Booking.Channel.AGENT),
        "booking_count": sum(r["n"] for r in by_channel.values()),
        "visitor_count": sum(r["visitors"] or 0 for r in by_channel.values()),
        "refunds": money(late_refunds(museum, start, end).aggregate(n=Sum("refund_amount"))["n"]),
    }
    pct = fee_percent_for(museum)
    total = values["gross_online"] + values["gross_kiosk"] + values["gross_counter"] + values["gross_agent"]
    fee = money(total * pct / Decimal(100))
    gst = money(fee * GST_ON_FEE_PERCENT / Decimal(100))
    # Counter cash already sits with the place; everything else was collected by the platform.
    collected_by_platform = values["gross_online"] + values["gross_kiosk"] + values["gross_agent"]
    values.update(
        platform_fee_percent=pct, platform_fee=fee, gst_on_fee=gst,
        net_payable=money(collected_by_platform - values["refunds"] - fee - gst),
    )
    return values


@transaction.atomic
def generate_settlements(*, start, end, by, museums=None):
    """Create (or refresh) draft settlements for every place with activity in [start, end].

    Places that already have an approved/paid settlement overlapping the period, or a draft for a different
    overlapping period, are skipped and reported.
    """
    if start > end:
        raise ValidationError({"from": "The start date must be on or before the end date."})
    if end >= timezone.localdate():
        raise ValidationError({"to": "Settle only completed days: the period must end before today."})
    if museums is None:
        active_ids = set(
            Booking.objects.filter(paid_at__gte=day_start(start), paid_at__lt=day_range(start, end)[1], status__in=LIVE)
            .values_list("museum_id", flat=True)
        ) | set(
            Booking.objects.filter(refund_amount__gt=0, cancelled_at__date__gte=start, cancelled_at__date__lte=end)
            .values_list("museum_id", flat=True)
        )
        museums = Museum.objects.filter(pk__in=active_ids)
    created, updated, skipped = [], [], []
    for museum in museums.order_by("name"):
        overlapping = Settlement.objects.select_for_update().filter(
            museum=museum, period_start__lte=end, period_end__gte=start
        )
        same = overlapping.filter(period_start=start, period_end=end).first()
        others = overlapping.exclude(pk=same.pk) if same else overlapping
        if others.exists() or (same and same.status != Settlement.Status.DRAFT):
            skipped.append({"museum": museum.name, "reason": "Already settled for an overlapping period."})
            continue
        values = compute_settlement(museum, start, end)
        if same:
            for k, v in values.items():
                setattr(same, k, v)
            same.save()
            updated.append(same)
        else:
            created.append(Settlement.objects.create(
                museum=museum, period_start=start, period_end=end, created_by=by, **values
            ))
    return created, updated, skipped
