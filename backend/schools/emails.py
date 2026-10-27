"""Emails to the school's contact teacher. Like notifications.services, errors are logged, never raised."""
import logging

from django.conf import settings
from django.core.mail import EmailMultiAlternatives
from django.template.loader import render_to_string

from notifications.models import NotificationLog

logger = logging.getLogger(__name__)

KIND_APPROVED = "school_trip_approved"
KIND_DECLINED = "school_trip_declined"
KIND_SCHOOL_STATUS = "school_status"


def _send(*, kind, subject, template, ctx, to, booking=None, user=None):
    base = dict(booking=booking, user=user, channel=NotificationLog.Channel.EMAIL, kind=kind, subject=subject[:200])
    if not to:
        return NotificationLog.objects.create(**base, recipient="", status=NotificationLog.Status.SKIPPED,
                                              error="No contact email")
    ctx = {
        **ctx,
        "support_email": settings.SUPPORT_EMAIL,
        "support_phone": settings.SUPPORT_PHONE,
        "frontend_url": settings.FRONTEND_URL,
        "portal_url": f"{settings.FRONTEND_URL}/schools",
    }
    try:
        text = render_to_string(f"schools/{template}.txt", ctx)
        html = render_to_string(f"schools/{template}.html", ctx)
        msg = EmailMultiAlternatives(subject, text, settings.DEFAULT_FROM_EMAIL, [to])
        msg.attach_alternative(html, "text/html")
        msg.send()
    except Exception as exc:
        logger.exception("School email %s to %s failed", kind, to)
        return NotificationLog.objects.create(**base, recipient=to, status=NotificationLog.Status.FAILED,
                                              error=str(exc)[:2000])
    return NotificationLog.objects.create(**base, recipient=to, status=NotificationLog.Status.SENT)


def send_trip_decision(trip_id):
    """Tell the teacher their trip was approved (with the pay link) or declined (with the reason)."""
    from .models import SchoolTrip

    trip = SchoolTrip.objects.select_related("school", "museum__city", "booking__slot", "requested_by").get(pk=trip_id)
    approved = trip.status == SchoolTrip.Status.APPROVED
    booking = trip.booking if approved else None
    ctx = {"trip": trip, "school": trip.school, "booking": booking, "approved": approved}
    if booking:
        ctx["checkout_url"] = f"{settings.FRONTEND_URL}/checkout/{booking.reference}"
        ctx["ticket_url"] = f"{settings.FRONTEND_URL}/tickets/{booking.reference}"
        ctx["needs_payment"] = booking.status == booking.Status.PENDING
    if approved:
        subject = f"Class trip approved - {trip.museum.name} on {trip.approved_date:%d %b %Y} ({trip.reference})"
    else:
        subject = f"Class trip request {trip.reference} declined - {trip.museum.name}"
    return _send(kind=KIND_APPROVED if approved else KIND_DECLINED, subject=subject, template="trip_decision",
                 ctx=ctx, to=trip.school.contact_email or trip.requested_by.email, booking=booking,
                 user=trip.requested_by)


def send_school_status(school_id):
    """Tell the teacher their school was verified or rejected."""
    from .models import School

    school = School.objects.select_related("owner").get(pk=school_id)
    verified = school.status == School.Status.VERIFIED
    subject = (f"{school.name} is verified - plan your class trips" if verified
               else f"School registration needs attention - {school.name}")
    return _send(kind=KIND_SCHOOL_STATUS, subject=subject, template="school_status",
                 ctx={"school": school, "verified": verified},
                 to=school.contact_email or school.owner.email, user=school.owner)
