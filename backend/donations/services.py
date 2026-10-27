"""Donation payment, receipt numbering, receipt access tokens and refunds."""
import secrets

from django.core import signing
from django.db import transaction
from django.utils import timezone
from django.utils.crypto import constant_time_compare
from rest_framework.exceptions import ValidationError

from . import payments
from .models import Donation, ReceiptCounter, financial_year, receipt_prefix

TOKEN_SALT = "donations.receipt"


# --- Guest access to a receipt (a signed token in the URL / email link) ----------------------------------

def access_token(donation):
    return signing.Signer(salt=TOKEN_SALT).signature(donation.reference)


def token_valid(donation, token):
    return bool(token) and constant_time_compare(access_token(donation), str(token))


def can_view(donation, user, token=None):
    """Owner (account or same email), an administrator, or anyone holding the signed link."""
    if token_valid(donation, token):
        return True
    if not (user and user.is_authenticated):
        return False
    if user.is_admin_role or (donation.user_id and donation.user_id == user.pk):
        return True
    return bool(user.email) and user.email.lower() == donation.donor_email.lower()


# --- Payment ------------------------------------------------------------------------------------------------

def assign_receipt_number(donation):
    """Next number in the financial year of the payment. Call inside a transaction with the donation locked."""
    if donation.receipt_number:
        return donation
    fy = financial_year(timezone.localdate(donation.paid_at))
    ReceiptCounter.objects.get_or_create(financial_year=fy)
    counter = ReceiptCounter.objects.select_for_update().get(financial_year=fy)
    counter.last_number += 1
    counter.save(update_fields=["last_number"])
    donation.receipt_fy = fy
    donation.receipt_seq = counter.last_number
    donation.receipt_number = f"{receipt_prefix()}/{fy}/{donation.receipt_seq:06d}"
    return donation


@transaction.atomic
def mark_paid(donation, method, payment_id=None, gateway=None):
    """Confirm the payment, number the receipt and email it (after commit)."""
    donation = Donation.objects.select_for_update().get(pk=donation.pk)
    if donation.status == Donation.Status.PAID:
        return donation
    donation.status = Donation.Status.PAID
    donation.payment_method = method
    donation.payment_id = payment_id or ("MOCK-" + secrets.token_hex(6).upper())
    donation.gateway = gateway or payments.MOCK
    donation.paid_at = timezone.now()
    assign_receipt_number(donation)
    donation.save(update_fields=[
        "status", "payment_method", "payment_id", "gateway", "paid_at", "receipt_fy", "receipt_seq", "receipt_number",
    ])
    from .emails import send_receipt_email

    pk = donation.pk
    transaction.on_commit(lambda: send_receipt_email(pk))
    return donation


def finalize_gateway_payment(order_id, payment_id, method=None):
    """Confirm a verified Razorpay payment (checkout callback or webhook). Safe to call twice.

    `order_id` is our Donation pk (like passes/bookings). A gift is accepted whenever the money arrives, even if
    the visitor's browser reported a failure first; a payment for a refunded donation is left alone.
    """
    donation = Donation.objects.get(pk=order_id)
    if donation.status == Donation.Status.PAID:
        return donation
    if donation.status == Donation.Status.REFUNDED and donation.payment_id == payment_id:
        return donation
    method = method or payments.payment_method(payment_id)
    return mark_paid(donation, method, payment_id=payment_id, gateway=payments.RAZORPAY)


@transaction.atomic
def mark_failed(donation):
    donation = Donation.objects.select_for_update().get(pk=donation.pk)
    if donation.status == Donation.Status.PENDING:
        donation.status = Donation.Status.FAILED
        donation.save(update_fields=["status"])
    return donation


@transaction.atomic
def refund(donation):
    """Admin: return a paid donation in full. The receipt number stays used (it is cancelled, not reissued)."""
    donation = Donation.objects.select_for_update().get(pk=donation.pk)
    if donation.status != Donation.Status.PAID:
        raise ValidationError("Only a paid donation can be refunded.")
    if donation.gateway == payments.RAZORPAY:
        result = payments.refund(donation)
        donation.refund_id = result.get("id", "")
    else:
        donation.refund_id = "MOCKRF-" + secrets.token_hex(5).upper()
    donation.status = Donation.Status.REFUNDED
    donation.refunded_at = timezone.now()
    donation.save(update_fields=["status", "refund_id", "refunded_at"])
    return donation
