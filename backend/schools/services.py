"""School trip pricing, date checks and approval.

Pricing and seat accounting reuse bookings.services: ticket prices on the visit date come from
effective_price (seasonal rules included), the school-group discount from group_discount_percent, and the
booking itself is made by create_booking with group_type="school", which locks the slot and enforces both
its free capacity and the group share (GROUP_SLOT_SHARE). So the estimate shown to the teacher is exactly
what that booking would cost before any staff quote.
"""
import datetime
from decimal import ROUND_HALF_UP, Decimal

from django.conf import settings
from django.db import transaction
from django.utils import timezone
from rest_framework.exceptions import ValidationError

from bookings import services as booking_services
from bookings.models import Booking
from museums.models import PriceRule

STUDENTS_PER_FREE_TEACHER = 20   # one teacher enters free per 20 students; also the minimum teacher ratio
MIN_STUDENTS = 10
MAX_STUDENTS = 400
PAY_BY_DAYS = 7


def teachers_needed(students):
    """At least one teacher per STUDENTS_PER_FREE_TEACHER students (rounded up)."""
    return -(-max(students, 0) // STUDENTS_PER_FREE_TEACHER)


def free_teachers(students, teachers):
    return min(teachers, teachers_needed(students))


def _find(tickets, word):
    return next((t for t in tickets if word in t.name.lower() and "foreign" not in t.name.lower()), None)


def school_tickets(museum):
    """The ticket types a school group is priced at: {"student", "child", "adult"} (child may be None).

    Students pay the place's Student ticket (or its Child ticket, or the adult ticket when neither exists);
    students young enough for the Child ticket pay that; teachers and helpers pay the Indian adult ticket.
    """
    tickets = list(museum.ticket_types.filter(is_active=True))
    adult = booking_services.default_group_ticket_type(museum)
    child = _find(tickets, "child")
    student = _find(tickets, "student") or child or adult
    return {"student": student, "child": child, "adult": adult}


def estimate(museum, visit_date, students, teachers, helpers=0, young_students=0):
    """Price a class visit. Returns lines, free teachers and totals (amounts are Decimals)."""
    tickets = school_tickets(museum)
    if tickets["adult"] is None:
        raise ValidationError({"museum": f"{museum.name} has no tickets on sale."})
    young_students = min(max(young_students, 0), students)
    if tickets["child"] is None:
        young_students = 0
    free = free_teachers(students, teachers)
    wanted = [
        ("student", tickets["student"], students - young_students),
        ("child", tickets["child"], young_students),
        ("adult", tickets["adult"], teachers - free + helpers),
    ]
    rules = list(PriceRule.objects.filter(museum=museum, is_active=True).order_by("-priority", "-id"))
    lines, by_ticket = [], {}
    for kind, ticket, qty in wanted:
        if not ticket or qty <= 0:
            continue
        if ticket.id in by_ticket:  # e.g. no student ticket: students and adults share one ticket
            by_ticket[ticket.id]["quantity"] += qty
            continue
        price = booking_services.effective_price(ticket, visit_date, rules)[0]
        line = {"kind": kind, "ticket_type": ticket, "name": ticket.name, "quantity": qty, "unit_price": price}
        by_ticket[ticket.id] = line
        lines.append(line)
    for line in lines:
        line["amount"] = line["unit_price"] * line["quantity"]
    subtotal = sum((line["amount"] for line in lines), Decimal(0))
    pct = booking_services.group_discount_percent(museum, Booking.GroupType.SCHOOL)
    # Same rounding as bookings.services.create_booking, so the booking total matches the estimate.
    discount = (subtotal * pct / Decimal(100)).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
    return {
        "lines": lines,
        "students": students,
        "young_students": young_students,
        "teachers": teachers,
        "helpers": helpers,
        "free_teachers": free,
        "people": students + teachers + helpers,
        "subtotal": subtotal,
        "discount_percent": pct,
        "discount": discount,
        "total": subtotal - discount,
        "tickets": tickets,
    }


def estimate_for_trip(trip, visit_date=None):
    return estimate(trip.museum, visit_date or trip.preferred_date, trip.students, trip.teachers, trip.helpers,
                    trip.young_students)


def visit_day_error(museum, day):
    """Why a class cannot visit `museum` on `day` (None when the day is fine)."""
    today = timezone.localdate()
    if day <= today:
        return "Pick a date in the future."
    if day > today + datetime.timedelta(days=settings.BOOKING_WINDOW_DAYS):
        return f"Visits can be booked up to {settings.BOOKING_WINDOW_DAYS} days ahead."
    if museum.is_closed_on(day):
        return f"{museum.name} is closed on {day:%A}s."
    closure = museum.closure_on(day)
    if closure["closed"]:
        return f"{museum.name} is closed on {day:%d %b %Y}: {closure['reason']}"
    return None


def candidate_slots(museum, day, preference, slot=None):
    """Slots to try for the class: the chosen one, else the preferred half of the day first, then the rest."""
    if slot is not None:
        return [slot]
    slots = list(museum.slots.filter(is_active=True).order_by("start_time"))
    closed = museum.closure_on(day)["slots"]
    slots = [s for s in slots if s.id not in closed]
    morning = [s for s in slots if s.start_time.hour < 12]
    afternoon = [s for s in slots if s.start_time.hour >= 12]
    return afternoon + morning if preference == "afternoon" else morning + afternoon


def slot_room(museum, day):
    """Free places and room left for groups in each active slot on `day` (for the staff approval screen)."""
    booked = booking_services.booked_visitors_by_slot(museum, day)
    groups = booking_services.group_seats_by_slot(museum, day)
    closed = museum.closure_on(day)["slots"]
    out = []
    for s in museum.slots.filter(is_active=True).order_by("start_time"):
        free = max(s.capacity - booked.get(s.id, 0), 0)
        out.append({
            "slot_id": s.id, "start": s.start_time, "end": s.end_time, "capacity": s.capacity, "free": free,
            "group_room": max(min(booking_services.group_cap(s) - groups.get(s.id, 0), free), 0),
            "closed": s.id in closed,
        })
    return out


def _pay_by(day, slot):
    today = timezone.localdate()
    end = timezone.make_aware(datetime.datetime.combine(
        min(today + datetime.timedelta(days=PAY_BY_DAYS), day), datetime.time(23, 59, 59)
    ))
    return min(end, booking_services.group_request_pay_by_limit(day, [slot]))


@transaction.atomic
def approve_trip(trip, *, by_user, visit_date, slot=None, quoted_amount=None, staff_note=None):
    """Create the class's pending group booking and mark the trip approved.

    The booking goes through bookings.services.create_booking (slot lock, capacity and group-share checks,
    school discount). A staff quote below the ticket total is applied as extra group discount, so the
    booking's total equals the quote. Free bookings (e.g. ASI sites free for children) are confirmed at once.
    """
    museum, school = trip.museum, trip.school
    error = visit_day_error(museum, visit_date)
    if error:
        raise ValidationError({"date": error})
    est = estimate_for_trip(trip, visit_date)
    items = [{"ticket_type": line["ticket_type"], "quantity": line["quantity"]} for line in est["lines"]]
    if not items:
        raise ValidationError("This trip has no tickets to book.")
    gross = est["subtotal"]
    if quoted_amount is not None and quoted_amount > gross:
        raise ValidationError({"quoted_amount": f"The quote can't be more than the ticket total of ₹{gross:.0f}."})

    booking, problems = None, []
    for candidate in candidate_slots(museum, visit_date, trip.slot_preference, slot):
        try:
            with transaction.atomic():
                booking = booking_services.create_booking(
                    user=trip.requested_by, museum=museum, slot=candidate, visit_date=visit_date, items=items,
                    visitor_name=school.contact_name, visitor_email=school.contact_email,
                    visitor_phone=school.contact_phone, group_type=Booking.GroupType.SCHOOL,
                    organisation_name=school.name[:150], escort_count=est["free_teachers"],
                )
            break
        except ValidationError as exc:
            problems.append(f"{candidate.start_time:%H:%M}: {_first_message(exc)}")
    if booking is None:
        detail = " ".join(problems) if slot is not None else ""
        raise ValidationError({"slot": (
            f"No slot on {visit_date:%d %b %Y} has room for this class of {est['people']} "
            f"(groups may use at most {int(settings.GROUP_SLOT_SHARE * 100)}% of a slot). "
            "Try the alternative date or another day. " + detail
        ).strip()})

    if booking.status == Booking.Status.PENDING:
        update = ["pay_by"]
        booking.pay_by = _pay_by(visit_date, booking.slot)
        if booking.pay_by <= timezone.now():
            raise ValidationError({"date": "The class's slot starts too soon to leave time for payment."})
        if quoted_amount is not None and quoted_amount != booking.total_amount:
            booking.discount_amount = gross - quoted_amount
            booking.total_amount = quoted_amount
            update += ["discount_amount", "total_amount"]
        booking.save(update_fields=update)
        if booking.total_amount == 0:
            booking_services.confirm_payment(booking, Booking.PaymentMethod.FREE)

    trip.status = trip.Status.APPROVED
    trip.approved_date = visit_date
    trip.booking = booking
    trip.quoted_amount = booking.total_amount
    trip.decided_by = by_user
    trip.decided_at = timezone.now()
    if staff_note is not None:
        trip.staff_note = staff_note
    trip.save()
    from .emails import send_trip_decision

    transaction.on_commit(lambda: send_trip_decision(trip.pk))
    return trip


def _first_message(exc):
    detail = exc.detail
    while isinstance(detail, (list, dict)):
        if not detail:
            return ""
        detail = next(iter(detail.values())) if isinstance(detail, dict) else detail[0]
    return str(detail)


def release_booking(trip):
    """Free the seats of a trip's unpaid booking (decline / cancel)."""
    if trip.booking_id and trip.booking.status == Booking.Status.PENDING:
        Booking.objects.filter(pk=trip.booking_id).update(status=Booking.Status.CANCELLED, cancelled_at=timezone.now())


def is_paid(trip):
    return bool(trip.booking_id and trip.booking.status in booking_services.PAID_STATUSES)
