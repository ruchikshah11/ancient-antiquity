"""Abandoned-booking recovery: find unpaid online bookings worth one friendly reminder, and track conversions."""
import datetime
from urllib.parse import urlencode

from django.conf import settings
from django.core import signing
from django.db.models import Q
from django.utils import timezone

from .models import EmailOptOut, RecoveryEmail

UNSUBSCRIBE_SALT = "analytics.recovery-unsubscribe"
MIN_AGE = datetime.timedelta(minutes=30)
MAX_AGE = datetime.timedelta(hours=24)
CONVERSION_WINDOW = datetime.timedelta(days=7)


def unsubscribe_token(email):
    return signing.dumps((email or "").strip().lower(), salt=UNSUBSCRIBE_SALT, compress=True)


def email_from_token(token):
    """The email address in a valid unsubscribe token, or None. Tokens don't expire (old emails must still work)."""
    try:
        return signing.loads(token, salt=UNSUBSCRIBE_SALT)
    except signing.BadSignature:
        return None


def unsubscribe_url(email):
    # The website proxies /api to Django (Vite in development, the web server in production).
    return f"{settings.FRONTEND_URL}/api/analytics/unsubscribe/{unsubscribe_token(email)}/"


def resume_url(booking):
    """The place page with the abandoned date and slot preselected (?date=&slot=)."""
    params = {
        "date": booking.visit_date.isoformat(), "slot": booking.slot_id,
        "utm_source": "recovery", "utm_medium": "email", "utm_campaign": "abandoned_booking",
    }
    return f"{settings.FRONTEND_URL}/museums/{booking.museum.slug}?{urlencode(params)}"


def recipient(booking):
    return (booking.visitor_email or getattr(booking.user, "email", "") or "").strip()


def candidates(now=None):
    """Abandoned bookings to remind now: newest per (user, place, visit date), deduplicated and filtered."""
    from bookings.models import Booking

    now = now or timezone.now()
    paid = [Booking.Status.CONFIRMED, Booking.Status.CHECKED_IN]
    qs = (
        Booking.objects.filter(
            status__in=[Booking.Status.PENDING, Booking.Status.EXPIRED],
            channel=Booking.Channel.ONLINE,
            is_group=False,
            paid_at__isnull=True,
            created_at__gte=now - MAX_AGE,
            created_at__lte=now - MIN_AGE,
            visit_date__gte=timezone.localdate(),
            museum__is_active=True,
        )
        .filter(recovery_email__isnull=True)
        .select_related("museum__city", "slot", "user")
        .order_by("-created_at")
    )
    seen = set()
    for booking in qs:
        key = (booking.user_id, booking.museum_id, booking.visit_date)
        if key in seen:
            continue
        seen.add(key)
        email = recipient(booking)
        if not email or booking.user.is_panel_user:
            continue
        # A still-held booking (e.g. approved group pay-by) is not abandoned yet.
        if booking.status == Booking.Status.PENDING and not booking.is_hold_expired:
            continue
        same = Booking.objects.filter(user_id=booking.user_id, museum_id=booking.museum_id)
        # Already completed (or a newer attempt still in progress) for the same place and date.
        if same.filter(visit_date=booking.visit_date).filter(
            Q(status__in=paid) | Q(paid_at__isnull=False)
            | Q(status=Booking.Status.PENDING, created_at__gt=booking.created_at)
        ).exists():
            continue
        # One reminder per visitor and place per conversion window, whatever the date.
        if RecoveryEmail.objects.filter(
            booking__user_id=booking.user_id, booking__museum_id=booking.museum_id,
            sent_at__gte=now - CONVERSION_WINDOW,
        ).exists():
            continue
        if EmailOptOut.is_opted_out(email):
            continue
        yield booking, email


def send_recovery_emails(now=None, dry_run=False):
    """Send the reminders. Returns (sent, failed, would_send) counts."""
    from notifications.models import NotificationLog
    from notifications.services import send_recovery_email

    sent = failed = would = 0
    for booking, email in list(candidates(now)):
        if dry_run:
            would += 1
            continue
        log = send_recovery_email(booking, email, resume_url(booking), unsubscribe_url(email))
        if log.status == NotificationLog.Status.SENT:
            RecoveryEmail.objects.get_or_create(booking=booking, defaults={"email": email})
            sent += 1
        else:
            failed += 1
    return sent, failed, would


def mark_conversions(queryset=None):
    """Link recovery emails to the paid booking that followed (same user and place, within 7 days)."""
    from bookings.models import Booking

    qs = (queryset if queryset is not None else RecoveryEmail.objects.all()).filter(converted_booking__isnull=True)
    updated = 0
    for rec in qs.select_related("booking"):
        match = (
            Booking.objects.filter(
                user_id=rec.booking.user_id, museum_id=rec.booking.museum_id, paid_at__isnull=False,
                created_at__gte=rec.booking.created_at, created_at__lte=rec.sent_at + CONVERSION_WINDOW,
            )
            .exclude(pk=rec.booking_id)
            .order_by("created_at")
            .first()
        )
        if match is None and rec.booking.paid_at:  # the abandoned booking itself was paid after all
            match = rec.booking
        if match is not None:
            rec.converted_booking = match
            rec.save(update_fields=["converted_booking"])
            updated += 1
    return updated
