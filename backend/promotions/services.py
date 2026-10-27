"""Promo codes and gift vouchers applied to pending bookings.

Amounts on a booking (all in rupees):
    gross (after any group discount) = total_amount + promo_discount + voucher_amount
    promo_discount  -> taken off by a promo code
    voucher_amount  -> paid with a gift voucher (deducted from its balance as soon as it is applied)
    total_amount    -> what is still to be paid online
"""
import logging
from decimal import ROUND_HALF_UP, Decimal

from django.conf import settings
from django.core.mail import send_mail
from django.db import transaction
from django.utils import timezone
from rest_framework.exceptions import ValidationError

from bookings import services as booking_services
from bookings.models import Booking

from .models import GiftVoucher, PromoCode, PromoRedemption, VoucherRedemption

log = logging.getLogger(__name__)

ACTIVE_STATUSES = (Booking.Status.PENDING, Booking.Status.CONFIRMED, Booking.Status.CHECKED_IN)
PAID_STATUSES = (Booking.Status.CONFIRMED, Booking.Status.CHECKED_IN)
ZERO = Decimal("0")


def normalize(code):
    return (code or "").strip().upper()


def active_redemptions(promo):
    """Redemptions that still count against the limits (booking pending or paid)."""
    return promo.redemptions.filter(booking__status__in=ACTIVE_STATUSES)


def promo_discount_for(promo, amount):
    if promo.discount_type == PromoCode.DiscountType.PERCENT:
        discount = (amount * promo.value / Decimal(100)).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
        if promo.max_discount is not None:
            discount = min(discount, promo.max_discount)
    else:
        discount = promo.value
    return max(min(discount, amount), ZERO)


def validate_promo(promo, booking, amount):
    """Raise ValidationError with a visitor-friendly message if the code can't be used on this booking."""
    now = timezone.now()
    if not promo.is_active:
        raise ValidationError({"code": "This promo code is no longer active."})
    if promo.valid_from and now < promo.valid_from:
        raise ValidationError({"code": "This promo code is not valid yet."})
    if promo.valid_to and now > promo.valid_to:
        raise ValidationError({"code": "This promo code has expired."})
    if amount < promo.min_order_amount:
        raise ValidationError({"code": f"This code needs a minimum order of ₹{promo.min_order_amount:.0f}."})
    if promo.applies_to == PromoCode.AppliesTo.INDIVIDUAL and booking.is_group:
        raise ValidationError({"code": "This code is not valid for group bookings."})
    if promo.applies_to == PromoCode.AppliesTo.GROUP and not booking.is_group:
        raise ValidationError({"code": "This code is only valid for group bookings."})
    if promo.scope == PromoCode.Scope.MUSEUMS and not promo.museums.filter(pk=booking.museum_id).exists():
        raise ValidationError({"code": "This code is not valid for this place."})
    if promo.scope == PromoCode.Scope.PLACE_TYPES and booking.museum.place_type not in promo.place_type_list:
        raise ValidationError({"code": "This code is not valid for this place."})
    used = active_redemptions(promo).exclude(booking=booking)
    if promo.usage_limit is not None and used.count() >= promo.usage_limit:
        raise ValidationError({"code": "This promo code has been fully used."})
    if promo.per_user_limit is not None and used.filter(user=booking.user).count() >= promo.per_user_limit:
        raise ValidationError({"code": "You have already used this promo code."})
    if promo.first_booking_only and Booking.objects.filter(
        user=booking.user, status__in=PAID_STATUSES
    ).exclude(pk=booking.pk).exists():
        raise ValidationError({"code": "This code is only for your first booking."})


def _locked_pending_booking(booking):
    booking = Booking.objects.select_for_update().select_related("museum").get(pk=booking.pk)
    if booking.status != Booking.Status.PENDING:
        raise ValidationError({"code": "Codes can only be changed before the booking is paid."})
    if booking.is_hold_expired:
        raise ValidationError({"code": "Your seat hold expired. Please book again."})
    return booking


def _save_amounts(booking):
    booking.total_amount = max(booking.total_amount, ZERO)
    booking.save(update_fields=["total_amount", "promo_code", "promo_discount", "voucher_amount"])
    if booking.total_amount == 0:
        booking_services.confirm_payment(booking, Booking.PaymentMethod.FREE)
    return booking


def _return_to_voucher(redemption, amount=None):
    """Give `amount` (default: all) of a voucher redemption back to the voucher balance."""
    voucher = GiftVoucher.objects.select_for_update().get(pk=redemption.voucher_id)
    full = amount is None or amount >= redemption.amount
    voucher.balance += redemption.amount if full else amount
    voucher.save(update_fields=["balance"])
    if full:
        redemption.reversed_at = timezone.now()  # keep the amount as a record
    else:
        redemption.amount -= amount
    redemption.save(update_fields=["amount", "reversed_at"])


def _open_voucher_redemption(booking):
    return booking.voucher_redemptions.filter(reversed_at__isnull=True).select_related("voucher").first()


@transaction.atomic
def apply_code(booking, raw_code):
    """Apply a promo code or a gift voucher (detected automatically) to a pending booking."""
    code = normalize(raw_code)
    if not code:
        raise ValidationError({"code": "Enter a promo code or gift voucher."})
    booking = _locked_pending_booking(booking)

    voucher = GiftVoucher.objects.select_for_update().filter(code=code).first()
    if voucher:
        return _apply_voucher(booking, voucher)
    promo = PromoCode.objects.filter(code__iexact=code).first()
    if promo:
        return _apply_promo(booking, promo)
    raise ValidationError({"code": "This code is not valid."})


def _apply_promo(booking, promo):
    if booking.promo_code_id == promo.pk:
        return booking
    if booking.promo_code_id:
        raise ValidationError({"code": "A promo code is already applied. Remove it first."})
    gross = booking.total_amount + booking.voucher_amount
    validate_promo(promo, booking, gross)
    discount = promo_discount_for(promo, gross)
    due = gross - discount
    if booking.voucher_amount > due:  # the voucher now covers more than needed: give the excess back
        excess = booking.voucher_amount - due
        redemption = _open_voucher_redemption(booking)
        if redemption:
            _return_to_voucher(redemption, excess)
        booking.voucher_amount -= excess
    booking.promo_code = promo
    booking.promo_discount = discount
    booking.total_amount = due - booking.voucher_amount
    PromoRedemption.objects.create(code=promo, booking=booking, user=booking.user, amount=discount)
    return _save_amounts(booking)


def _apply_voucher(booking, voucher):
    if booking.voucher_amount > 0:
        raise ValidationError({"code": "A gift voucher is already applied. Remove it first."})
    if not voucher.is_active:
        raise ValidationError({"code": "This gift voucher is no longer active."})
    if voucher.is_expired:
        raise ValidationError({"code": "This gift voucher has expired."})
    if voucher.balance <= 0:
        raise ValidationError({"code": "This gift voucher has no balance left."})
    if booking.total_amount <= 0:
        raise ValidationError({"code": "There is nothing left to pay on this booking."})
    use = min(voucher.balance, booking.total_amount)
    voucher.balance -= use
    voucher.save(update_fields=["balance"])
    VoucherRedemption.objects.create(voucher=voucher, booking=booking, amount=use)
    booking.voucher_amount = use
    booking.total_amount -= use
    return _save_amounts(booking)


@transaction.atomic
def remove_code(booking, kind=None):
    """Remove the promo code and/or voucher ("promo", "voucher" or None for both) while still pending."""
    booking = _locked_pending_booking(booking)
    if kind in (None, "", "promo") and booking.promo_code_id:
        PromoRedemption.objects.filter(booking=booking, code_id=booking.promo_code_id).delete()
        booking.total_amount += booking.promo_discount
        booking.promo_code = None
        booking.promo_discount = ZERO
    if kind in (None, "", "voucher") and booking.voucher_amount > 0:
        _release_vouchers(booking)
        booking.total_amount += booking.voucher_amount
        booking.voucher_amount = ZERO
    booking.save(update_fields=["total_amount", "promo_code", "promo_discount", "voucher_amount"])
    return booking


def _release_vouchers(booking):
    released = ZERO
    for redemption in booking.voucher_redemptions.select_for_update().filter(reversed_at__isnull=True):
        released += redemption.amount
        _return_to_voucher(redemption)
    return released


@transaction.atomic
def release_for_booking(booking):
    """Return any gift-voucher money held by this booking to the voucher(s). Safe to call twice.

    Call it when an unpaid booking expires or is cancelled, or when a paid booking is cancelled with a
    refund (the voucher part goes back to the voucher; the rest is refunded to the original payment).
    The booking's amounts are left as they were, as a record of what happened.
    """
    return _release_vouchers(booking)


def voucher_refund_due(booking):
    """Should the voucher part of this (expired/cancelled) booking go back to the voucher?"""
    if booking.status not in (Booking.Status.EXPIRED, Booking.Status.CANCELLED):
        return False
    if not booking.paid_at:
        return True  # never paid: the hold simply ended
    if booking.refund_status in (Booking.RefundStatus.PENDING, Booking.RefundStatus.PROCESSED):
        return True  # cash part refunded -> voucher part comes back too
    if booking.total_amount == 0 and booking.status == Booking.Status.CANCELLED and booking.cancelled_at:
        # Fully paid by voucher: nothing to refund online, so apply the same time rule to the voucher part.
        if booking.channel == Booking.Channel.COUNTER:
            return False
        hours_left = (booking.slot_starts_at - booking.cancelled_at).total_seconds() / 3600
        return hours_left >= settings.REFUND_FULL_BEFORE_HOURS
    return False


def release_stale_vouchers():
    """Catch-up for bookings expired in bulk (QuerySet.update skips signals): free their voucher money."""
    booking_services.expire_stale_bookings()
    stale = Booking.objects.filter(
        status__in=[Booking.Status.EXPIRED, Booking.Status.CANCELLED], paid_at__isnull=True,
        voucher_redemptions__reversed_at__isnull=True,
    ).distinct()
    for booking in stale:
        release_for_booking(booking)


def email_voucher(voucher):
    if not voucher.recipient_email:
        return False
    greeting = f"Dear {voucher.recipient_name}," if voucher.recipient_name else "Hello,"
    sender = f" from {voucher.purchaser_name}" if voucher.purchaser_name else ""
    lines = [
        greeting, "",
        f"You have received an Ancient Antiquity gift voucher{sender} worth ₹{voucher.initial_value:.0f}.",
        "",
        f"Voucher code: {voucher.code}",
        f"Valid until: {voucher.valid_until:%d %b %Y}",
    ]
    if voucher.message:
        lines += ["", f"Message: {voucher.message}"]
    lines += ["", "Enter the code at checkout when you book a visit to any museum, fort, palace or monument."]
    try:
        return bool(send_mail(
            "Your Ancient Antiquity gift voucher", "\n".join(lines), settings.DEFAULT_FROM_EMAIL,
            [voucher.recipient_email], fail_silently=True,
        ))
    except Exception:  # pragma: no cover - fail_silently covers SMTP errors; keep issuing robust anyway
        log.exception("Could not email gift voucher %s", voucher.code)
        return False
