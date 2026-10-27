"""Donation receipt email. Like notifications.services, a mail failure never breaks a payment."""
import logging

from django.conf import settings
from django.core.mail import send_mail
from django.template.loader import render_to_string

from .models import Donation
from .words import rupees_in_words

logger = logging.getLogger(__name__)


def receipt_url(donation):
    from .services import access_token

    return f"{settings.FRONTEND_URL}/donations/{donation.reference}?token={access_token(donation)}"


def receipt_context(donation):
    return {
        "donation": donation,
        "amount_words": rupees_in_words(donation.amount),
        "trust_name": settings.DONATION_TRUST_NAME or "Ancient Antiquity Heritage Foundation",
        "trust_pan": settings.DONATION_TRUST_PAN,
        "registration_80g": settings.DONATION_80G_NUMBER,
        "receipt_url": receipt_url(donation),
        "support_email": settings.SUPPORT_EMAIL,
        "support_phone": getattr(settings, "SUPPORT_PHONE", ""),
        "frontend_url": settings.FRONTEND_URL,
    }


def send_receipt_email(donation_or_pk):
    """Email the receipt (with a link to the printable copy). Returns True when sent."""
    pk = getattr(donation_or_pk, "pk", donation_or_pk)
    try:
        donation = Donation.objects.select_related("museum").get(pk=pk)
        if donation.status != Donation.Status.PAID or not donation.donor_email:
            return False
        ctx = receipt_context(donation)
        subject = f"Thank you for your donation - receipt {donation.receipt_number}"
        send_mail(
            subject,
            render_to_string("donations/receipt_email.txt", ctx),
            settings.DEFAULT_FROM_EMAIL,
            [donation.donor_email],
            html_message=render_to_string("donations/receipt_email.html", ctx),
        )
        return True
    except Exception:
        logger.exception("Donation receipt email for %s failed", pk)
        return False
