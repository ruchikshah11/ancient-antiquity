"""Booking and account notifications (email, SMS, WhatsApp and web push).

Every public function here swallows its own errors: a broken SMTP server or SMS gateway must never
break a booking, a payment or a cancellation. Each attempt is recorded in NotificationLog instead.
"""
import base64
import io
import json
import logging
import re
import urllib.parse
import urllib.request
from email.mime.image import MIMEImage

from django.conf import settings
from django.core.mail import EmailMultiAlternatives
from django.template.loader import render_to_string

from .models import NotificationLog

logger = logging.getLogger(__name__)

KIND_CONFIRMED = "confirmed"
KIND_CANCELLED = "cancelled"
KIND_RESEND = "resend"
KIND_PASSWORD_RESET = "password_reset"
KIND_REMINDER = "reminder"            # the day before the visit (send_visit_reminders)
KIND_REMINDER_SOON = "reminder_soon"  # a few hours before the slot (send_visit_reminders --hours-before N)
KIND_WAITLIST = "waitlist"            # seats freed up for a waitlisted visitor (events app)
REMINDER_KINDS = (KIND_REMINDER, KIND_REMINDER_SOON)

QR_CID = "ticket-qr"
SMS_TIMEOUT_SECONDS = 10


# ---------------------------------------------------------------- helpers

def _log(**fields):
    """Write a NotificationLog row; never raise (logging must not become the failure)."""
    try:
        return NotificationLog.objects.create(**fields)
    except Exception:  # pragma: no cover - DB unavailable etc.
        logger.exception("Could not write NotificationLog %s", fields)
        return NotificationLog(**fields)


def _load_booking(booking):
    """Accept a Booking or its pk; always read fresh from the DB (refund fields may have changed)."""
    from bookings.models import Booking

    pk = booking.pk if hasattr(booking, "pk") else booking
    return (
        Booking.objects.select_related("museum__city__state", "slot", "event_session__event", "user")
        .prefetch_related("items").get(pk=pk)
    )


def ticket_url(booking):
    return f"{settings.FRONTEND_URL}/tickets/{booking.reference}"


def qr_png(data):
    """PNG bytes of a QR code for `data` (the booking reference, as scanned at the gate)."""
    import qrcode

    img = qrcode.make(data, box_size=8, border=2)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def _support_context():
    return {
        "support_email": settings.SUPPORT_EMAIL,
        "support_phone": settings.SUPPORT_PHONE,
        "frontend_url": settings.FRONTEND_URL,
    }


def _booking_context(booking, kind):
    return {
        **_support_context(),
        "booking": booking,
        "kind": kind,
        "items": list(booking.items.all()),
        "ticket_url": ticket_url(booking),
        "qr_cid": QR_CID,
        "has_refund": booking.refund_amount and booking.refund_amount > 0,
        "is_reminder": kind in REMINDER_KINDS,
        "is_soon": kind == KIND_REMINDER_SOON,
    }


# ---------------------------------------------------------------- email

def _subject(booking, kind):
    if kind == KIND_CANCELLED:
        return f"Booking cancelled - {booking.reference} ({booking.museum.name})"
    if kind == KIND_REMINDER:
        return f"Reminder: your visit to {booking.museum.name} is tomorrow - {booking.reference}"
    if kind == KIND_REMINDER_SOON:
        return (f"Reminder: your visit to {booking.museum.name} starts at "
                f"{booking.slot_start_time:%H:%M} - {booking.reference}")
    return f"Your ticket for {booking.museum.name} - {booking.reference}"


def send_booking_email(booking, kind, user=None):
    """Send the confirmation/cancellation email for a booking. Returns the NotificationLog row."""
    booking = _load_booking(booking)
    subject = _subject(booking, kind)
    base = dict(booking=booking, user=user, channel=NotificationLog.Channel.EMAIL, kind=kind, subject=subject)
    if not booking.visitor_email:
        return _log(**base, recipient="", status=NotificationLog.Status.SKIPPED, error="No visitor email")
    try:
        ctx = _booking_context(booking, kind)
        # Cancelled tickets are not valid at the gate, so they get no QR code.
        ctx["show_qr"] = kind != KIND_CANCELLED
        text = render_to_string("notifications/booking_email.txt", ctx)
        html = render_to_string("notifications/booking_email.html", ctx)
        msg = EmailMultiAlternatives(subject, text, settings.DEFAULT_FROM_EMAIL, [booking.visitor_email])
        msg.attach_alternative(html, "text/html")
        if ctx["show_qr"]:
            msg.mixed_subtype = "related"  # lets mail clients resolve cid: references to the inline image
            image = MIMEImage(qr_png(booking.reference), "png")
            image.add_header("Content-ID", f"<{QR_CID}>")
            image.add_header("Content-Disposition", "inline", filename=f"{booking.reference}.png")
            msg.attach(image)
        msg.send()
    except Exception as exc:
        logger.exception("Booking email %s for %s failed", kind, booking.reference)
        return _log(**base, recipient=booking.visitor_email, status=NotificationLog.Status.FAILED, error=str(exc)[:2000])
    return _log(**base, recipient=booking.visitor_email, status=NotificationLog.Status.SENT)


# ---------------------------------------------------------------- SMS

def _normalise_phone(phone):
    """Digits with country code (Indian 10-digit numbers get 91 prefixed)."""
    digits = re.sub(r"\D", "", phone or "")
    if len(digits) == 11 and digits.startswith("0"):
        digits = digits[1:]
    if len(digits) == 10:
        digits = "91" + digits
    return digits


def _post(url, data, headers):
    req = urllib.request.Request(url, data=data, headers=headers, method="POST")
    with urllib.request.urlopen(req, timeout=SMS_TIMEOUT_SECONDS) as resp:
        body = resp.read().decode("utf-8", "replace")
        if resp.status >= 300:
            raise RuntimeError(f"HTTP {resp.status}: {body[:300]}")
        return body


def _send_msg91(phone, text):
    payload = json.dumps({
        "sender": settings.SMS_SENDER_ID,
        "route": "4",  # transactional
        "country": "91",
        "sms": [{"message": text, "to": [phone]}],
    }).encode()
    _post("https://api.msg91.com/api/v2/sendsms", payload,
          {"authkey": settings.SMS_API_KEY, "Content-Type": "application/json"})


def _send_twilio(phone, text):
    sid = settings.TWILIO_ACCOUNT_SID
    auth = base64.b64encode(f"{sid}:{settings.TWILIO_AUTH_TOKEN}".encode()).decode()
    data = urllib.parse.urlencode({"To": "+" + phone, "From": settings.TWILIO_FROM, "Body": text}).encode()
    _post(f"https://api.twilio.com/2010-04-01/Accounts/{sid}/Messages.json", data,
          {"Authorization": f"Basic {auth}", "Content-Type": "application/x-www-form-urlencoded"})


def _provider_ready(provider):
    if provider == "msg91":
        return bool(settings.SMS_API_KEY)
    if provider == "twilio":
        return bool(settings.TWILIO_ACCOUNT_SID and settings.TWILIO_AUTH_TOKEN and settings.TWILIO_FROM)
    return False


def _is_sample_phone(number):
    """True when a normalised number belongs to a sample-data account (never texted; see notifications.mail)."""
    from accounts.models import User

    return bool(number) and User.objects.filter(is_sample=True, phone__endswith=number[-10:]).exists()


def send_sms(phone, text, booking=None, user=None, kind=""):
    """Send one SMS through the configured provider; console (log only) when none is configured."""
    base = dict(booking=booking, user=user, channel=NotificationLog.Channel.SMS, kind=kind, subject=text[:200])
    number = _normalise_phone(phone)
    if not number:
        return _log(**base, recipient="", status=NotificationLog.Status.SKIPPED, error="No phone number")
    if _is_sample_phone(number):
        return _log(**base, recipient=number, status=NotificationLog.Status.SKIPPED, error="Sample-data account")
    provider = (settings.SMS_PROVIDER or "console").lower()
    try:
        if provider in ("msg91", "twilio") and _provider_ready(provider):
            (_send_msg91 if provider == "msg91" else _send_twilio)(number, text)
        else:
            if provider != "console":
                logger.warning("SMS provider %r selected but not configured; logging SMS instead", provider)
            logger.info("SMS to +%s: %s", number, text)
            if provider != "console":
                return _log(**base, recipient=number, status=NotificationLog.Status.SKIPPED,
                            error=f"{provider} keys missing; logged only")
    except Exception as exc:
        logger.exception("SMS %s to %s failed", kind, number)
        return _log(**base, recipient=number, status=NotificationLog.Status.FAILED, error=str(exc)[:2000])
    return _log(**base, recipient=number, status=NotificationLog.Status.SENT)


def _booking_sms_text(booking, kind):
    when = f"{booking.visit_date:%d %b %Y} {booking.slot_start_time:%H:%M}"
    if kind == KIND_REMINDER:
        return (f"Ancient Antiquity reminder: your visit to {booking.museum.name} is tomorrow, {when}, "
                f"{booking.total_visitors} visitor(s). Ticket: {ticket_url(booking)}")
    if kind == KIND_REMINDER_SOON:
        return (f"Ancient Antiquity reminder: your visit to {booking.museum.name} starts at "
                f"{booking.slot_start_time:%H:%M} today, {booking.total_visitors} visitor(s). "
                f"Ticket: {ticket_url(booking)}")
    if kind == KIND_CANCELLED:
        text = f"Ancient Antiquity: booking {booking.reference} for {booking.museum.name} on {when} is cancelled."
        if booking.refund_amount and booking.refund_amount > 0:
            text += f" Refund Rs {booking.refund_amount:.2f} ({booking.get_refund_status_display().lower()})."
        return text
    return (f"Ancient Antiquity: booking {booking.reference} confirmed for {booking.museum.name}, {when}, "
            f"{booking.total_visitors} visitor(s). Ticket: {ticket_url(booking)}")


# ---------------------------------------------------------------- WhatsApp

WHATSAPP_API = "https://graph.facebook.com/v20.0/{phone_number_id}/messages"


def whatsapp_enabled():
    """WhatsApp is on unless WHATSAPP_PROVIDER is "off"/"none"/empty ("console" logs only, "meta" sends)."""
    return (getattr(settings, "WHATSAPP_PROVIDER", "") or "").lower() in ("console", "meta")


def _send_whatsapp_meta(phone, text):
    """WhatsApp Cloud API free-form text message.

    Meta only delivers free-form text inside a 24-hour customer-service window. Business-initiated
    messages (tickets, reminders) need an approved message template - see notifications/README.md.
    """
    payload = json.dumps({
        "messaging_product": "whatsapp",
        "recipient_type": "individual",
        "to": phone,
        "type": "text",
        "text": {"preview_url": True, "body": text},
    }).encode()
    _post(WHATSAPP_API.format(phone_number_id=settings.WHATSAPP_PHONE_NUMBER_ID), payload,
          {"Authorization": f"Bearer {settings.WHATSAPP_TOKEN}", "Content-Type": "application/json"})


def send_whatsapp(phone, text, booking=None, user=None, kind=""):
    """Send one WhatsApp message through the configured provider; console (log only) by default."""
    base = dict(booking=booking, user=user, channel=NotificationLog.Channel.WHATSAPP, kind=kind, subject=text[:200])
    number = _normalise_phone(phone)
    if not number:
        return _log(**base, recipient="", status=NotificationLog.Status.SKIPPED, error="No phone number")
    if _is_sample_phone(number):
        return _log(**base, recipient=number, status=NotificationLog.Status.SKIPPED, error="Sample-data account")
    provider = (getattr(settings, "WHATSAPP_PROVIDER", "") or "console").lower()
    try:
        if provider == "meta":
            if not (settings.WHATSAPP_TOKEN and settings.WHATSAPP_PHONE_NUMBER_ID):
                logger.warning("WhatsApp provider 'meta' selected but token/phone number id missing; logging instead")
                logger.info("WhatsApp to +%s: %s", number, text)
                return _log(**base, recipient=number, status=NotificationLog.Status.SKIPPED,
                            error="meta keys missing; logged only")
            _send_whatsapp_meta(number, text)
        else:
            logger.info("WhatsApp to +%s: %s", number, text)
    except Exception as exc:
        logger.exception("WhatsApp %s to %s failed", kind, number)
        return _log(**base, recipient=number, status=NotificationLog.Status.FAILED, error=str(exc)[:2000])
    return _log(**base, recipient=number, status=NotificationLog.Status.SENT)


# ---------------------------------------------------------------- web push

def push_configured():
    return bool(getattr(settings, "VAPID_PUBLIC_KEY", "") and getattr(settings, "VAPID_PRIVATE_KEY", ""))


def send_push(user, title, body, url="/", booking=None, kind=""):
    """Web-push a notification to every browser `user` subscribed. Returns how many were delivered.

    Subscriptions the push service reports as gone (404/410) are deleted. One NotificationLog row per user.
    """
    from .models import PushSubscription

    if user is None or getattr(user, "is_sample", False) or not push_configured():
        return 0
    subs = list(PushSubscription.objects.filter(user=user))
    if not subs:
        return 0
    from pywebpush import WebPushException, webpush

    data = json.dumps({"title": title, "body": body, "url": url, "tag": booking.reference if booking else kind})
    sent, errors = 0, []
    for sub in subs:
        try:
            webpush(
                subscription_info=sub.as_subscription_info(), data=data,
                vapid_private_key=settings.VAPID_PRIVATE_KEY,
                vapid_claims={"sub": settings.VAPID_SUBJECT}, ttl=12 * 3600, timeout=SMS_TIMEOUT_SECONDS,
            )
            sent += 1
        except WebPushException as exc:
            code = getattr(getattr(exc, "response", None), "status_code", None)
            if code in (404, 410):
                sub.delete()  # browser unsubscribed or the subscription expired
            errors.append(f"{code or ''} {exc}"[:300])
        except Exception as exc:
            logger.exception("Web push to %s failed", sub.endpoint[:60])
            errors.append(str(exc)[:300])
    status = NotificationLog.Status.SENT if sent else NotificationLog.Status.FAILED
    _log(booking=booking, user=user, channel=NotificationLog.Channel.PUSH, kind=kind, subject=title[:200],
         recipient=f"{len(subs)} browser(s)", status=status, error="\n".join(errors)[:2000])
    return sent


# ---------------------------------------------------------------- public API

def _send_booking(booking, kind):
    try:
        booking = _load_booking(booking)
    except Exception:
        logger.exception("Could not load booking %s for %s notification", booking, kind)
        return
    send_booking_email(booking, kind)
    if booking.visitor_phone:
        try:
            send_sms(booking.visitor_phone, _booking_sms_text(booking, kind), booking=booking, kind=kind)
        except Exception:  # send_sms already guards itself; belt and braces for text building
            logger.exception("SMS %s for %s failed", kind, booking.reference)
        if kind != KIND_CANCELLED and whatsapp_enabled():
            try:
                send_whatsapp(booking.visitor_phone, _booking_sms_text(booking, kind), booking=booking, kind=kind)
            except Exception:
                logger.exception("WhatsApp %s for %s failed", kind, booking.reference)
    # No phone: nothing to log - email log already records the attempt (counter sales often have neither).


def send_booking_confirmed(booking):
    """Ticket email (with QR) + SMS after a booking is confirmed. `booking` may be an instance or pk."""
    _send_booking(booking, KIND_CONFIRMED)


def send_booking_cancelled(booking):
    """Cancellation email + SMS, mentioning the refund when one was issued."""
    _send_booking(booking, KIND_CANCELLED)


def reminder_already_sent(booking, kind=KIND_REMINDER):
    return NotificationLog.objects.filter(booking=booking, kind=kind).exists()


def send_visit_reminder(booking, kind=KIND_REMINDER):
    """Email + SMS + WhatsApp + web push reminding the visitor of an upcoming visit.

    Returns False (and sends nothing) when this reminder kind was already sent for the booking.
    """
    booking = _load_booking(booking)
    if reminder_already_sent(booking, kind):
        return False
    send_booking_email(booking, kind)
    if booking.visitor_phone:
        text = _booking_sms_text(booking, kind)
        try:
            send_sms(booking.visitor_phone, text, booking=booking, kind=kind)
            if whatsapp_enabled():
                send_whatsapp(booking.visitor_phone, text, booking=booking, kind=kind)
        except Exception:
            logger.exception("Reminder SMS/WhatsApp for %s failed", booking.reference)
    if booking.channel == "online":
        when = ("tomorrow" if kind == KIND_REMINDER else "today") + f" at {booking.slot_start_time:%H:%M}"
        try:
            send_push(booking.user, f"Visit {booking.museum.name} {when}",
                      f"{booking.total_visitors} visitor(s) - tap to open your ticket {booking.reference}.",
                      url=f"/tickets/{booking.reference}", booking=booking, kind=kind)
        except Exception:
            logger.exception("Reminder push for %s failed", booking.reference)
    return True


def _waitlist_text(entry, url):
    if entry.event_session_id:
        session = entry.event_session
        what = f"{session.event.title} at {entry.museum.name} on {session.date:%d %b %Y} {session.start_time:%H:%M}"
    else:
        what = f"{entry.museum.name} on {entry.visit_date:%d %b %Y}"
        if entry.slot_id:
            what += f" {entry.slot.start_time:%H:%M}"
    return (f"Ancient Antiquity: seats just freed up for {what} ({entry.quantity} wanted). "
            f"Seats go to whoever books first: {url}")


def send_waitlist_available(entry, url):
    """Tell a waitlisted visitor that seats freed up, on the channels they chose (email/SMS/WhatsApp/push).

    Never raises; each attempt is logged with kind "waitlist".
    """
    user = entry.user
    try:
        text = _waitlist_text(entry, url)
    except Exception:
        logger.exception("Could not build waitlist message for entry %s", entry.pk)
        return
    subject = f"Seats available - {entry.museum.name}"[:200]
    if entry.wants("email") and user.email:
        base = dict(user=user, channel=NotificationLog.Channel.EMAIL, kind=KIND_WAITLIST, subject=subject,
                    recipient=user.email)
        try:
            body = (f"Hello {user.first_name or 'there'},\n\n{text}\n\nYou are receiving this because you joined "
                    f"the waitlist. Seats are not held for you, so book soon.\n\n{settings.SUPPORT_EMAIL}")
            EmailMultiAlternatives(subject, body, settings.DEFAULT_FROM_EMAIL, [user.email]).send()
            _log(**base, status=NotificationLog.Status.SENT)
        except Exception as exc:
            logger.exception("Waitlist email to %s failed", user.email)
            _log(**base, status=NotificationLog.Status.FAILED, error=str(exc)[:2000])
    phone = getattr(user, "phone", "") or ""
    if phone:
        try:
            if entry.wants("sms"):
                send_sms(phone, text, user=user, kind=KIND_WAITLIST)
            if entry.wants("whatsapp") and whatsapp_enabled():
                send_whatsapp(phone, text, user=user, kind=KIND_WAITLIST)
        except Exception:
            logger.exception("Waitlist SMS/WhatsApp for entry %s failed", entry.pk)
    if entry.wants("push"):
        try:
            path = url[len(settings.FRONTEND_URL):] if url.startswith(settings.FRONTEND_URL) else url
            send_push(user, subject, text, url=path or "/", kind=KIND_WAITLIST)
        except Exception:
            logger.exception("Waitlist push for entry %s failed", entry.pk)


def send_password_reset(user, link):
    """Email a password-reset link. Returns the NotificationLog row."""
    subject = "Reset your Ancient Antiquity password"
    base = dict(user=user, channel=NotificationLog.Channel.EMAIL, kind=KIND_PASSWORD_RESET,
                subject=subject, recipient=user.email)
    try:
        ctx = {**_support_context(), "user": user, "link": link}
        text = render_to_string("notifications/password_reset.txt", ctx)
        html = render_to_string("notifications/password_reset.html", ctx)
        msg = EmailMultiAlternatives(subject, text, settings.DEFAULT_FROM_EMAIL, [user.email])
        msg.attach_alternative(html, "text/html")
        msg.send()
    except Exception as exc:
        logger.exception("Password reset email to %s failed", user.email)
        return _log(**base, status=NotificationLog.Status.FAILED, error=str(exc)[:2000])
    return _log(**base, status=NotificationLog.Status.SENT)


# ---------------------------------------------------------------- abandoned-booking recovery (analytics app)

KIND_RECOVERY = "recovery"


def send_recovery_email(booking, email, resume_link, unsubscribe_link):
    """One friendly "your tickets are waiting" email for an unpaid booking. Returns the NotificationLog row."""
    subject = f"Your tickets for {booking.museum.name} are waiting"
    base = dict(booking=booking, user=booking.user, channel=NotificationLog.Channel.EMAIL, kind=KIND_RECOVERY,
                subject=subject, recipient=email)
    try:
        ctx = {**_support_context(), "booking": booking, "museum": booking.museum, "link": resume_link,
               "unsubscribe_link": unsubscribe_link,
               "name": (booking.visitor_name or "").split(" ")[0] or getattr(booking.user, "first_name", "")}
        text = render_to_string("notifications/recovery_email.txt", ctx)
        html = render_to_string("notifications/recovery_email.html", ctx)
        msg = EmailMultiAlternatives(
            subject, text, settings.DEFAULT_FROM_EMAIL, [email],
            headers={"List-Unsubscribe": f"<{unsubscribe_link}>", "List-Unsubscribe-Post": "List-Unsubscribe=One-Click"},
        )
        msg.attach_alternative(html, "text/html")
        msg.send()
    except Exception as exc:
        logger.exception("Recovery email for booking %s failed", booking.pk)
        return _log(**base, status=NotificationLog.Status.FAILED, error=str(exc)[:2000])
    return _log(**base, status=NotificationLog.Status.SENT)
