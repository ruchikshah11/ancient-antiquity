"""Event-session seat accounting, event bookings and the waitlist."""
import logging
from decimal import Decimal

from django.conf import settings
from django.db import transaction
from django.db.models import Sum
from django.utils import timezone
from rest_framework.exceptions import ValidationError

from bookings.models import Booking, BookingItem
from bookings.services import confirm_payment, seat_holding_filter

from .models import EventSession, WaitlistEntry

logger = logging.getLogger(__name__)


# --- Event sessions --------------------------------------------------------------------------------------

def taken_by_session(session_ids):
    """Seats held per event session id (paid bookings + unpaid ones inside the hold window)."""
    rows = (
        Booking.objects.filter(event_session_id__in=list(session_ids)).filter(seat_holding_filter())
        .values("event_session_id").annotate(n=Sum("total_visitors"))
    )
    return {r["event_session_id"]: r["n"] for r in rows}


def session_free(session):
    taken = taken_by_session([session.pk]).get(session.pk, 0)
    return max(session.capacity - taken, 0)


def session_closed_reason(session):
    """Why this session can't be booked on its date by the closures calendar (whole-day closures only)."""
    info = session.event.museum.closure_on(session.date)
    if not info["closed"]:
        return ""
    return info["reason"] or "Closed"


def session_bookable(session, now=None):
    now = now or timezone.now()
    return (
        session.is_active and session.event.is_active and session.event.museum.is_active
        and session.starts_at > now
    )


@transaction.atomic
def create_event_booking(*, user, session, items, visitor_name, visitor_email="", visitor_phone=""):
    """Pending booking for an event session; paid through the normal booking checkout.

    items: [{"price": EventPrice, "quantity": int}] (quantities > 0).
    """
    session = EventSession.objects.select_for_update().select_related("event__museum").get(pk=session.pk)
    event = session.event
    if not session_bookable(session):
        raise ValidationError({"session": "This session is no longer on sale."})
    reason = session_closed_reason(session)
    if reason:
        raise ValidationError({"session": f"{event.museum.name} is closed on {session.date:%d %b %Y}: {reason}"})
    if any(i["price"].event_id != event.id for i in items):
        raise ValidationError({"items": "Ticket does not belong to this event."})
    requested = sum(i["quantity"] for i in items)
    if requested <= 0:
        raise ValidationError({"items": "Select at least one ticket."})
    if requested > settings.MAX_TICKETS_PER_BOOKING:
        raise ValidationError({"items": f"Maximum {settings.MAX_TICKETS_PER_BOOKING} tickets per booking."})
    free = session_free(session)
    if requested > free:
        raise ValidationError({"session": f"Only {free} seat(s) left in this session."})

    total = sum((Decimal(i["price"].price) * i["quantity"] for i in items), Decimal(0))
    booking = Booking.objects.create(
        user=user,
        museum=event.museum,
        slot=None,
        event_session=session,
        visit_date=session.date,
        total_visitors=requested,
        total_amount=total,
        visitor_name=visitor_name,
        visitor_email=visitor_email,
        visitor_phone=visitor_phone,
    )
    BookingItem.objects.bulk_create([
        BookingItem(booking=booking, event_price=i["price"], ticket_name=i["price"].name[:60],
                    quantity=i["quantity"], unit_price=i["price"].price)
        for i in items
    ])
    if total == 0:
        confirm_payment(booking, Booking.PaymentMethod.FREE)
    # The visitor got seats: their waitlist entry for this session (if any) is done.
    WaitlistEntry.objects.filter(
        user=user, event_session=session, status__in=[WaitlistEntry.Status.WAITING, WaitlistEntry.Status.NOTIFIED]
    ).update(status=WaitlistEntry.Status.BOOKED)
    return booking


# --- Waitlist --------------------------------------------------------------------------------------------

def slot_free(slot, visit_date):
    taken = (
        Booking.objects.filter(slot=slot, visit_date=visit_date).filter(seat_holding_filter())
        .aggregate(n=Sum("total_visitors"))["n"] or 0
    )
    return max(slot.capacity - taken, 0)


def free_seats_for_entry(entry):
    if entry.event_session_id:
        return session_free(entry.event_session)
    return slot_free(entry.slot, entry.visit_date)


def book_url(entry):
    base = settings.FRONTEND_URL
    if entry.event_session_id:
        return f"{base}/events/{entry.event_session.event.slug}?date={entry.visit_date:%Y-%m-%d}"
    return f"{base}/museums/{entry.museum.slug}?date={entry.visit_date:%Y-%m-%d}"


def expire_past_entries():
    today = timezone.localdate()
    return WaitlistEntry.objects.filter(
        visit_date__lt=today, status__in=[WaitlistEntry.Status.WAITING, WaitlistEntry.Status.NOTIFIED]
    ).update(status=WaitlistEntry.Status.EXPIRED)


def notify_waitlist_for(*, slot_id=None, event_session_id=None, visit_date=None):
    """Seats may have freed up in this slot (on visit_date) or event session: tell waiting visitors.

    Waiting entries are taken in FIFO order; each one whose party fits in the seats not yet promised to an
    earlier notified entry is notified (email/SMS/WhatsApp/push) and marked notified. Never raises.
    Returns the number of entries notified.
    """
    try:
        return _notify_waitlist_for(slot_id=slot_id, event_session_id=event_session_id, visit_date=visit_date)
    except Exception:
        logger.exception("Waitlist notification failed (slot=%s session=%s date=%s)", slot_id, event_session_id, visit_date)
        return 0


def _notify_waitlist_for(*, slot_id, event_session_id, visit_date):
    from notifications.services import send_waitlist_available

    expire_past_entries()
    qs = WaitlistEntry.objects.filter(status=WaitlistEntry.Status.WAITING).select_related(
        "user", "museum", "slot", "event_session__event"
    )
    if event_session_id:
        qs = qs.filter(event_session_id=event_session_id)
    elif slot_id and visit_date:
        qs = qs.filter(slot_id=slot_id, visit_date=visit_date, event_session__isnull=True)
    else:
        return 0
    entries = list(qs)
    if not entries:
        return 0
    free = free_seats_for_entry(entries[0])
    if event_session_id:
        session = entries[0].event_session
        if not session_bookable(session):
            return 0
    elif visit_date < timezone.localdate():
        return 0
    notified = 0
    now = timezone.now()
    for entry in entries:
        if free <= 0:
            break
        if entry.quantity > free:
            continue  # a smaller party further down the list may still fit
        free -= entry.quantity
        entry.status = WaitlistEntry.Status.NOTIFIED
        entry.notified_at = now
        entry.save(update_fields=["status", "notified_at"])
        send_waitlist_available(entry, book_url(entry))
        notified += 1
    return notified


def notify_for_bookings(rows):
    """rows: iterable of (slot_id, event_session_id, visit_date) whose seats were released."""
    today = timezone.localdate()
    for slot_id, session_id, visit_date in set(rows):
        if visit_date and visit_date < today:
            continue
        notify_waitlist_for(slot_id=slot_id, event_session_id=session_id, visit_date=visit_date)


def mark_booked_for(booking):
    """A booking for a slot the visitor was waiting for: close their waitlist entry."""
    if booking.slot_id:
        WaitlistEntry.objects.filter(
            user_id=booking.user_id, slot_id=booking.slot_id, visit_date=booking.visit_date,
            status__in=[WaitlistEntry.Status.WAITING, WaitlistEntry.Status.NOTIFIED],
        ).update(status=WaitlistEntry.Status.BOOKED)
