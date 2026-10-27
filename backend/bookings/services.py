"""Seat accounting shared by availability, booking creation and payment."""
import secrets
from datetime import timedelta
from decimal import ROUND_HALF_UP, Decimal

from django.conf import settings
from django.db import transaction
from django.db.models import Q, Sum
from django.utils import timezone
from rest_framework.exceptions import ValidationError

from museums.models import TimeSlot

from . import payments
from .models import Booking, BookingAddOn, BookingItem, GateScan


def hold_cutoff():
    return timezone.now() - timedelta(minutes=settings.BOOKING_HOLD_MINUTES)


def seat_holding_filter():
    """Bookings that occupy capacity: paid ones, plus unpaid ones still inside the hold window.

    Approved large-group bookings (pay_by set) hold their seats until pay_by instead of the short hold.
    """
    return (
        Q(status__in=[Booking.Status.CONFIRMED, Booking.Status.CHECKED_IN])
        | Q(status=Booking.Status.PENDING, pay_by__isnull=True, created_at__gte=hold_cutoff())
        | Q(status=Booking.Status.PENDING, pay_by__gt=timezone.now())
    )


def booked_visitors_by_slot(museum, visit_date):
    rows = (
        Booking.objects.filter(museum=museum, visit_date=visit_date)
        .filter(seat_holding_filter())
        .values("slot_id")
        .annotate(n=Sum("total_visitors"))
    )
    return {r["slot_id"]: r["n"] for r in rows}


def expire_stale_bookings():
    stale = Booking.objects.filter(status=Booking.Status.PENDING).filter(
        Q(pay_by__isnull=True, created_at__lt=hold_cutoff()) | Q(pay_by__lte=timezone.now())
    )
    request_ids = set(stale.exclude(group_request=None).values_list("group_request_id", flat=True))
    with_voucher = list(stale.filter(voucher_amount__gt=0).values_list("pk", flat=True))
    released = list(stale.values_list("slot_id", "event_session_id", "visit_date"))
    stale.update(status=Booking.Status.EXPIRED)
    if released:
        # .update() fires no signals: tell waitlisted visitors about the freed seats (events app).
        from events.services import notify_for_bookings

        notify_for_bookings(released)
    if with_voucher:
        # .update() fires no signals, so give gift-voucher money back to the vouchers explicitly.
        from promotions.services import release_for_booking

        for booking in Booking.objects.filter(pk__in=with_voucher):
            release_for_booking(booking)
    if request_ids:
        from grouprequests.models import GroupRequest

        for group_request in GroupRequest.objects.filter(pk__in=request_ids):
            sync_group_request_status(group_request)


def group_seats_by_slot(museum, visit_date):
    """Seats held by group bookings per slot (groups are capped at GROUP_SLOT_SHARE of each slot)."""
    rows = (
        Booking.objects.filter(museum=museum, visit_date=visit_date, is_group=True)
        .filter(seat_holding_filter())
        .values("slot_id")
        .annotate(n=Sum("total_visitors"))
    )
    return {r["slot_id"]: r["n"] for r in rows}


def group_cap(slot):
    return int(slot.capacity * settings.GROUP_SLOT_SHARE)


def max_free_escorts(group_type, participants):
    """School/college groups get one free escort per GROUP_ESCORTS_PER students (rounded up)."""
    if group_type not in Booking.EDUCATIONAL:
        return 0
    return -(-participants // settings.GROUP_ESCORTS_PER)


def group_discount_percent(museum, group_type):
    return museum.school_discount_percent if group_type in Booking.EDUCATIONAL else museum.group_discount_percent


# --- Seasonal / peak pricing and calendar closures ------------------------------------------------------

def effective_price(ticket_type, visit_date, rules=None):
    """Ticket price on visit_date after the highest-priority matching PriceRule (base price if none).

    `rules` may be passed (the museum's active rules, highest priority first) to avoid a query per ticket.
    Returns (price, rule or None).
    """
    from museums.models import PriceRule

    if rules is None:
        rules = PriceRule.objects.filter(museum_id=ticket_type.museum_id, is_active=True).order_by("-priority", "-id")
    for rule in rules:
        if rule.matches(ticket_type, visit_date):
            return rule.apply(ticket_type.price), rule
    return ticket_type.price, None


def prices_for(museum, visit_date):
    """Every active ticket's price on visit_date, for the booking card."""
    from museums.models import PriceRule

    rules = list(PriceRule.objects.filter(museum=museum, is_active=True).order_by("-priority", "-id"))
    out = []
    for tk in museum.ticket_types.filter(is_active=True):
        price, rule = effective_price(tk, visit_date, rules)
        out.append({
            "ticket_type": tk.id, "name": tk.name, "base_price": tk.price, "price": price,
            "rule": rule.name if rule else None,
        })
    return out


def closure_error(museum, slot, visit_date):
    """Why a booking for this place/slot/date is not allowed by the closures calendar (None if open)."""
    info = museum.closure_on(visit_date)
    if info["closed"]:
        return {"visit_date": f"{museum.name} is closed on {visit_date:%d %b %Y}: {info['reason']}"}
    if slot.id in info["slots"]:
        return {"slot": f"The {slot.start_time:%H:%M} slot is closed on {visit_date:%d %b %Y}: {info['slots'][slot.id]}"}
    return None


def check_not_closed(museum, slot, visit_date):
    error = closure_error(museum, slot, visit_date)
    if error:
        raise ValidationError(error)


@transaction.atomic
def create_booking(
    *, user, museum, slot, visit_date, items, visitor_name, visitor_email="", visitor_phone="",
    channel=Booking.Channel.ONLINE, payment_method=None, check_in=False,
    group_type="", organisation_name="", escort_count=0,
):
    """Online bookings start pending; counter sales are paid on the spot and confirmed at once.

    Passing group_type makes it a group booking: the group discount applies, free escorts are added,
    and the group must fit inside the slot's group share as well as its remaining capacity.
    A visitor with a Heritage Card valid on visit_date gets its discount on individual online bookings
    (not on group, counter, kiosk or tour-operator bookings).
    """
    # Lock the slot row so two concurrent requests can't both take the last seats.
    slot = TimeSlot.objects.select_for_update().get(pk=slot.pk)
    check_not_closed(museum, slot, visit_date)
    is_group = bool(group_type)
    requested = sum(i["quantity"] for i in items) + escort_count
    holding = Booking.objects.filter(slot=slot, visit_date=visit_date).filter(seat_holding_filter())
    taken = holding.aggregate(n=Sum("total_visitors"))["n"] or 0
    remaining = slot.capacity - taken
    if requested > remaining:
        raise ValidationError(
            {"slot": f"Only {max(remaining, 0)} ticket(s) left in this slot."}
        )
    if is_group:
        group_taken = holding.filter(is_group=True).aggregate(n=Sum("total_visitors"))["n"] or 0
        group_left = min(group_cap(slot) - group_taken, remaining)
        if requested > group_left:
            raise ValidationError({
                "slot": f"This slot has room for {max(group_left, 0)} more people in groups. "
                        "Please pick another slot or split the group."
            })

    unit_prices = {i["ticket_type"].id: effective_price(i["ticket_type"], visit_date)[0] for i in items}
    subtotal = sum(unit_prices[i["ticket_type"].id] * i["quantity"] for i in items)
    discount = Decimal(0)
    if is_group:
        pct = group_discount_percent(museum, group_type)
        discount = (subtotal * pct / Decimal(100)).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
    membership, member_discount = None, Decimal(0)
    if channel == Booking.Channel.ONLINE and not is_group:
        from memberships.services import booking_benefit

        membership, member_discount = booking_benefit(
            user, museum, visit_date, [(unit_prices[i["ticket_type"].id], i["quantity"]) for i in items]
        )
    total = subtotal - discount - member_discount
    booking = Booking.objects.create(
        user=user,
        museum=museum,
        slot=slot,
        visit_date=visit_date,
        total_visitors=requested,
        total_amount=total,
        discount_amount=discount,
        membership=membership,
        membership_discount=member_discount,
        is_group=is_group,
        group_type=group_type,
        organisation_name=organisation_name,
        escort_count=escort_count,
        visitor_name=visitor_name,
        visitor_email=visitor_email,
        visitor_phone=visitor_phone,
        channel=channel,
        sold_by=user if channel == Booking.Channel.COUNTER else None,
    )
    BookingItem.objects.bulk_create([
        BookingItem(
            booking=booking,
            ticket_type=i["ticket_type"],
            ticket_name=i["ticket_type"].name,
            quantity=i["quantity"],
            unit_price=unit_prices[i["ticket_type"].id],
        )
        for i in items
    ])
    if total == 0:
        confirm_payment(booking, Booking.PaymentMethod.FREE)
    elif channel == Booking.Channel.COUNTER:
        confirm_payment(booking, payment_method)
    if check_in:
        mark_checked_in(booking, user)
    return booking


# --- Add-ons chosen at checkout ---------------------------------------------------------------------------

@transaction.atomic
def set_booking_addons(booking, items):
    """Replace a pending booking's add-ons with `items` ([{"addon": id, "quantity": n}]) and re-price it.

    Checks that each add-on belongs to the booking's place and is on sale, the per-booking limit and the
    daily stock (counted over bookings that still hold seats on the visit date, this one excluded).
    """
    from addons.models import AddOn
    from addons.services import remaining_on

    booking = Booking.objects.select_for_update(of=("self",)).select_related("museum", "promo_code").get(pk=booking.pk)
    if booking.status != Booking.Status.PENDING:
        raise ValidationError({"addons": "Add-ons can only be changed before the booking is paid."})
    if booking.is_hold_expired:
        raise ValidationError({"addons": "Your seat hold expired. Please book again."})
    wanted = {}
    for item in items:
        if item["quantity"] > 0:
            wanted[item["addon"]] = wanted.get(item["addon"], 0) + item["quantity"]
    # Locking the add-on rows makes two checkouts wait for each other on the last wheelchair.
    found = {a.id: a for a in AddOn.objects.select_for_update().filter(pk__in=wanted)}
    lines = []
    for addon_id, quantity in wanted.items():
        addon = found.get(addon_id)
        if addon is None or addon.museum_id != booking.museum_id:
            raise ValidationError({"addons": f"Add-on {addon_id} is not offered at {booking.museum.name}."})
        if not addon.is_active:
            raise ValidationError({"addons": f"{addon.name} is no longer offered."})
        limit = addon.quantity_limit(booking.total_visitors)
        if quantity > limit:
            raise ValidationError({"addons": f"{addon.name}: at most {limit} per booking."})
        left = remaining_on(addon, booking.visit_date, exclude_booking=booking)
        if left is not None and quantity > left:
            raise ValidationError({
                "addons": f"{addon.name}: only {left} left on {booking.visit_date:%d %b %Y}." if left
                else f"{addon.name} is sold out on {booking.visit_date:%d %b %Y}."
            })
        lines.append(BookingAddOn(
            booking=booking, addon=addon, name=addon.name, kind=addon.kind, quantity=quantity, unit_price=addon.price,
        ))
    booking.addons.all().delete()
    BookingAddOn.objects.bulk_create(lines)
    booking.addons_amount = sum((line.line_total for line in lines), Decimal(0))
    return recalculate_totals(booking)


def recalculate_totals(booking):
    """Re-derive what is still to pay after the add-ons changed (booking must be locked and pending).

    Order: tickets - group discount - Heritage Card discount + add-ons, then the promo code, then the gift
    voucher. The promo code is taken off that whole amount (add-ons included), the same base promotions uses
    when the code is applied. A voucher that now covers more than is due gives the excess back to the voucher.
    """
    from promotions import services as promo_services
    from promotions.models import PromoRedemption

    tickets = sum((i.unit_price * i.quantity for i in booking.items.all()), Decimal(0))
    gross = tickets - booking.discount_amount - booking.membership_discount + booking.addons_amount
    if booking.promo_code_id:
        promo = booking.promo_code
        if gross < promo.min_order_amount:
            raise ValidationError({"addons": f"Promo code {promo.code} needs a minimum order of "
                                             f"₹{promo.min_order_amount:.0f}. Remove the code first."})
        booking.promo_discount = promo_services.promo_discount_for(promo, gross)
        PromoRedemption.objects.filter(booking=booking, code=promo).update(amount=booking.promo_discount)
    due = gross - booking.promo_discount
    if booking.voucher_amount > due:
        excess = booking.voucher_amount - due
        redemption = promo_services._open_voucher_redemption(booking)
        if redemption:
            promo_services._return_to_voucher(redemption, excess)
        booking.voucher_amount -= excess
    booking.total_amount = max(due - booking.voucher_amount, Decimal(0))
    booking.save(update_fields=["addons_amount", "promo_discount", "voucher_amount", "total_amount"])
    if booking.total_amount == 0:
        confirm_payment(booking, Booking.PaymentMethod.FREE)
    return booking


def mark_checked_in(booking, by_user, at=None, admitted=None, scan_id=None, offline=False):
    """Admit `admitted` people (default: everyone still outside). Groups may arrive in several parts.

    A repeated scan_id (offline device re-sending the same scan) is ignored, so syncing is safe to retry.
    Returns the number of people admitted by this call.
    """
    if scan_id and GateScan.objects.filter(scan_id=scan_id).exists():
        return 0
    at = at or timezone.now()
    count = booking.remaining_to_enter if admitted is None else min(admitted, booking.remaining_to_enter)
    if count <= 0:
        return 0
    booking.visitors_arrived += count
    if booking.status != Booking.Status.CHECKED_IN:
        booking.status = Booking.Status.CHECKED_IN
        booking.checked_in_at = at
        booking.checked_in_by = by_user
    booking.save(update_fields=["status", "checked_in_at", "checked_in_by", "visitors_arrived"])
    GateScan.objects.create(booking=booking, admitted=count, scanned_at=at, scanned_by=by_user,
                            scan_id=scan_id or None, offline=offline)
    return count


def confirm_payment(booking, method, payment_id=None, gateway=None):
    """Mark a booking paid. payment_id/gateway come from Razorpay; otherwise a demo/counter id is generated."""
    booking.status = Booking.Status.CONFIRMED
    booking.payment_method = method
    if payment_id:
        booking.payment_id = payment_id
    elif method == Booking.PaymentMethod.FREE:
        booking.payment_id = ""
    elif booking.channel == Booking.Channel.COUNTER:
        booking.payment_id = "CTR-" + secrets.token_hex(5).upper()
    else:
        booking.payment_id = "MOCK-" + secrets.token_hex(6).upper()
    booking.gateway = gateway or ("" if method == Booking.PaymentMethod.FREE or booking.channel == Booking.Channel.COUNTER else payments.MOCK)
    booking.paid_at = timezone.now()
    booking.save(update_fields=["status", "payment_method", "payment_id", "paid_at", "gateway"])
    if booking.group_request_id:
        sync_group_request_status(booking.group_request)
    return booking


def seats_free_for(booking):
    """Could this booking's party still fit in its slot or event session (ignoring the booking itself)?"""
    if booking.event_session_id:
        from events.models import EventSession

        place = EventSession.objects.select_for_update().get(pk=booking.event_session_id)
        holding = Booking.objects.filter(event_session=place)
    else:
        place = TimeSlot.objects.select_for_update().get(pk=booking.slot_id)
        holding = Booking.objects.filter(slot=place, visit_date=booking.visit_date)
    taken = (
        holding.exclude(pk=booking.pk).filter(seat_holding_filter()).aggregate(n=Sum("total_visitors"))["n"] or 0
    )
    return place.capacity - taken >= booking.total_visitors


class PaymentRefunded(ValidationError):
    """Raised after a late payment was refunded (the refund itself is already saved on the booking)."""


def finalize_gateway_payment(booking_id, payment_id, method):
    """Confirm a verified Razorpay payment. Safe to call twice (checkout callback + webhook).

    If the 15-minute hold ran out while the visitor was paying, the booking is confirmed when seats are
    still free; otherwise the payment is refunded automatically and PaymentRefunded is raised. The error is
    raised only after the transaction has committed, so the recorded refund is never rolled back.
    """
    booking, refunded = _finalize_gateway_payment(booking_id, payment_id, method)
    if refunded:
        raise PaymentRefunded(
            "Your seat hold expired and the slot filled up, so the payment has been refunded automatically. "
            "Please book another slot."
            if booking.status != Booking.Status.CANCELLED
            else "This booking was already cancelled, so the payment has been refunded automatically."
        )
    return booking


@transaction.atomic
def _finalize_gateway_payment(booking_id, payment_id, method):
    """Returns (booking, refunded)."""
    booking = Booking.objects.select_for_update().get(pk=booking_id)
    if booking.status in (Booking.Status.CONFIRMED, Booking.Status.CHECKED_IN):
        return booking, False  # already handled (e.g. by the webhook)
    if booking.payment_id == payment_id and booking.refund_status:
        return booking, True  # this late payment was already refunded (checkout callback + webhook)
    held = booking.status == Booking.Status.PENDING and not booking.is_hold_expired
    if held or (booking.status in (Booking.Status.PENDING, Booking.Status.EXPIRED) and seats_free_for(booking)):
        return confirm_payment(booking, method, payment_id=payment_id, gateway=payments.RAZORPAY), False
    # Seats were released to someone else, or the visitor cancelled meanwhile: give the money back.
    booking.payment_id = payment_id
    booking.gateway = payments.RAZORPAY
    if booking.status != Booking.Status.CANCELLED:
        booking.status = Booking.Status.EXPIRED
    booking.save(update_fields=["payment_id", "gateway", "status"])
    issue_refund(booking, booking.total_amount)
    return booking, True


def issue_refund(booking, amount):
    """Refund through the gateway the booking was paid with (demo gateway: marked refunded at once)."""
    if amount <= 0:
        return booking
    booking.refund_amount = amount
    if booking.payment_method == Booking.PaymentMethod.ON_ACCOUNT:
        # Tour-operator booking on credit: no money was taken, so nothing is refunded here.
        # Cancelling removes it from the agent's balance (recalculated by the partners app).
        return booking
    if booking.payment_method == Booking.PaymentMethod.BANK_TRANSFER:
        # Paid by bank transfer/invoice: the money must be sent back manually by the finance team.
        booking.refund_id = ""
        booking.refund_status = Booking.RefundStatus.PENDING
    elif booking.gateway == payments.RAZORPAY:
        refund = payments.refund(booking, amount)
        booking.refund_id = refund.get("id", "")
        booking.refund_status = (
            Booking.RefundStatus.PROCESSED if refund.get("status") == "processed" else Booking.RefundStatus.PENDING
        )
    else:
        booking.refund_id = "MOCKRF-" + secrets.token_hex(5).upper()
        booking.refund_status = Booking.RefundStatus.PROCESSED
    booking.save(update_fields=["refund_amount", "refund_id", "refund_status"])
    return booking


@transaction.atomic
def cancel_booking(booking):
    """Cancel and refund according to the policy (full refund up to REFUND_FULL_BEFORE_HOURS before the slot)."""
    booking = Booking.objects.select_for_update(of=("self",)).select_related("slot", "event_session").get(pk=booking.pk)
    refundable = booking.refundable_amount
    booking.status = Booking.Status.CANCELLED
    booking.cancelled_at = timezone.now()
    booking.save(update_fields=["status", "cancelled_at"])
    issue_refund(booking, refundable)
    if booking.group_request_id:
        sync_group_request_status(booking.group_request)
    return booking


# --- Large group requests (more than GROUP_MAX_SIZE people, approved by staff) -------------------------

PAID_STATUSES = (Booking.Status.CONFIRMED, Booking.Status.CHECKED_IN)


def individual_reserve(slot):
    """Seats in each slot kept free for individual visitors when planning a large group (default 20%)."""
    share = Decimal(str(getattr(settings, "GROUP_REQUEST_INDIVIDUAL_RESERVE", 0.20)))
    return int((slot.capacity * share).to_integral_value(rounding="ROUND_CEILING"))


def default_group_ticket_type(museum):
    """The ticket large groups are priced at unless staff choose otherwise: the Indian adult ticket."""
    tickets = list(museum.ticket_types.filter(is_active=True))
    for t in tickets:
        name = t.name.lower()
        if "adult" in name and "foreign" not in name:
            return t
    paid = [t for t in tickets if t.price > 0 and "foreign" not in t.name.lower()]
    return (paid or tickets or [None])[0]


def plan_group_split(museum, visit_date, people, preferred_time="any"):
    """Suggest how to spread `people` over consecutive slots on visit_date.

    Each slot can take up to its free capacity minus a reserve kept for individuals. Picks the run of
    consecutive slots that needs the fewest slots (earliest first) and balances people across it.
    When nothing fits, returns the largest consecutive run with fits=False.
    """
    now = timezone.localtime()
    slots = [
        s for s in museum.slots.filter(is_active=True).order_by("start_time")
        if not (visit_date == now.date() and s.start_time <= now.time())
    ]
    if preferred_time == "morning":
        slots = [s for s in slots if s.start_time.hour < 12]
    elif preferred_time == "afternoon":
        slots = [s for s in slots if s.start_time.hour >= 12]
    booked = booked_visitors_by_slot(museum, visit_date)
    usable = []
    for s in slots:
        free = max(s.capacity - booked.get(s.id, 0), 0)
        usable.append({"slot": s, "free": free, "usable": max(free - individual_reserve(s), 0)})

    best = None      # (slot count, start, end) of the shortest run that fits
    largest = None   # (covered, start, end) of the biggest run, for the "does not fit" answer
    for i in range(len(usable)):
        covered, j = 0, i
        while j < len(usable) and usable[j]["usable"] > 0:  # runs stay consecutive
            covered += usable[j]["usable"]
            j += 1
            if covered >= people:
                break
        if covered >= people and (best is None or j - i < best[0]):
            best = (j - i, i, j)
        if covered and (largest is None or covered > largest[0]):
            largest = (covered, i, j)
    fits = best is not None
    allocations = []
    if fits:
        allocations = _balance(usable[best[1]:best[2]], people)
    elif largest:
        chosen = usable[largest[1]:largest[2]]
        allocations = _balance(chosen, sum(u["usable"] for u in chosen))
    return {
        "fits": fits,
        "people": people,
        "allocated": sum(a["people"] for a in allocations),
        "preferred_time": preferred_time,
        "slots": [
            {"slot_id": u["slot"].id, "start": u["slot"].start_time, "end": u["slot"].end_time,
             "capacity": u["slot"].capacity, "free": u["free"], "usable": u["usable"]}
            for u in usable
        ],
        "allocations": allocations,
    }


def _balance(chosen, people):
    """Spread people as evenly as possible over the chosen slots without exceeding each slot's usable seats."""
    shares = [0] * len(chosen)
    left = people
    open_idx = [k for k, u in enumerate(chosen) if u["usable"] > 0]
    while left > 0 and open_idx:
        each = max(left // len(open_idx), 1)
        for k in list(open_idx):
            take = min(each, chosen[k]["usable"] - shares[k], left)
            shares[k] += take
            left -= take
            if shares[k] >= chosen[k]["usable"]:
                open_idx.remove(k)
            if left <= 0:
                break
    return [
        {"slot_id": u["slot"].id, "start": u["slot"].start_time, "end": u["slot"].end_time, "people": shares[k]}
        for k, u in enumerate(chosen) if shares[k] > 0
    ]


def group_request_pay_by_limit(visit_date, slots):
    """Payment must arrive before the group's first slot starts."""
    from datetime import datetime

    first = min(s.start_time for s in slots)
    return timezone.make_aware(datetime.combine(visit_date, first))


@transaction.atomic
def create_group_request_bookings(*, group_request, visit_date, allocations, discount_percent, pay_by):
    """Create one pending booking per allocation for an approved large-group request.

    allocations: [{"slot": TimeSlot, "items": [{"ticket_type", "quantity"}], "escorts": int}]
    Bypasses the instant-group size limits and the GROUP_SLOT_SHARE cap (staff approved it), but still locks
    each slot and checks its free capacity. Escorts enter free. Bookings belong to the requester so they can
    pay online through the normal checkout; seats are held until pay_by. Tickets are charged at their
    effective price on visit_date (PriceRule), like every other booking.
    """
    from museums.models import PriceRule

    museum = group_request.museum
    pct = Decimal(discount_percent)
    rules = list(PriceRule.objects.filter(museum=museum, is_active=True).order_by("-priority", "-id"))
    bookings = []
    for alloc in sorted(allocations, key=lambda a: a["slot"].start_time):
        slot = TimeSlot.objects.select_for_update().get(pk=alloc["slot"].pk)
        if slot.museum_id != museum.id:
            raise ValidationError({"allocations": f"Slot {slot.pk} does not belong to {museum.name}."})
        items = [i for i in alloc["items"] if i["quantity"] > 0]
        participants = sum(i["quantity"] for i in items)
        escorts = alloc.get("escorts", 0)
        requested = participants + escorts
        if participants <= 0:
            raise ValidationError({"allocations": f"The {slot.start_time:%H:%M} slot has no participants."})
        taken = (
            Booking.objects.filter(slot=slot, visit_date=visit_date).filter(seat_holding_filter())
            .aggregate(n=Sum("total_visitors"))["n"] or 0
        )
        remaining = slot.capacity - taken
        if requested > remaining:
            raise ValidationError({
                "allocations": f"The {slot.start_time:%H:%M} slot has only {max(remaining, 0)} free place(s) "
                               f"but {requested} were allocated."
            })
        unit_prices = {i["ticket_type"].id: effective_price(i["ticket_type"], visit_date, rules)[0] for i in items}
        subtotal = sum(unit_prices[i["ticket_type"].id] * i["quantity"] for i in items)
        discount = (subtotal * pct / Decimal(100)).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
        booking = Booking.objects.create(
            user=group_request.requester,
            museum=museum,
            slot=slot,
            visit_date=visit_date,
            total_visitors=requested,
            total_amount=subtotal - discount,
            discount_amount=discount,
            is_group=True,
            group_type=group_request.group_type,
            organisation_name=group_request.organisation_name,
            escort_count=escorts,
            visitor_name=group_request.contact_name,
            visitor_email=group_request.contact_email,
            visitor_phone=group_request.contact_phone,
            pay_by=pay_by,
            group_request=group_request,
        )
        BookingItem.objects.bulk_create([
            BookingItem(booking=booking, ticket_type=i["ticket_type"], ticket_name=i["ticket_type"].name,
                        quantity=i["quantity"], unit_price=unit_prices[i["ticket_type"].id])
            for i in items
        ])
        bookings.append(booking)
    return bookings


def sync_group_request_status(group_request):
    """Keep an approved request's status in step with its bookings: all paid -> paid; all lapsed -> expired."""
    from grouprequests.models import GroupRequest

    if group_request.status not in (GroupRequest.Status.APPROVED, GroupRequest.Status.PAID,
                                    GroupRequest.Status.EXPIRED):
        return group_request
    statuses = list(group_request.bookings.values_list("status", flat=True))
    if not statuses:
        return group_request
    live = [s for s in statuses if s != Booking.Status.CANCELLED]
    if live and all(s in PAID_STATUSES for s in live):
        new = GroupRequest.Status.PAID
    elif any(s == Booking.Status.PENDING for s in live):
        new = GroupRequest.Status.APPROVED
    elif not live:
        new = GroupRequest.Status.CANCELLED
    else:
        new = GroupRequest.Status.EXPIRED  # some or all of the bookings were not paid in time
    if new != group_request.status:
        group_request.status = new
        group_request.save(update_fields=["status", "updated_at"])
    return group_request


@transaction.atomic
def mark_group_request_paid(group_request, payment_id=""):
    """Bank transfer / invoice received: confirm every unpaid booking of the request.

    Bookings whose pay_by lapsed are still confirmed if their seats are free; otherwise nothing is confirmed.
    """
    bookings = list(
        group_request.bookings.select_for_update()
        .filter(status__in=[Booking.Status.PENDING, Booking.Status.EXPIRED])
    )
    if not bookings:
        raise ValidationError("There are no unpaid bookings on this request.")
    for booking in bookings:
        if booking.status == Booking.Status.EXPIRED and not seats_free_for(booking):
            raise ValidationError(
                f"Booking {booking.reference} expired and its slot has filled up. Re-plan the visit instead."
            )
    ref = payment_id or "BT-" + secrets.token_hex(5).upper()
    for booking in bookings:
        confirm_payment(booking, Booking.PaymentMethod.BANK_TRANSFER, payment_id=ref, gateway="bank")
    group_request.refresh_from_db()
    return sync_group_request_status(group_request)
