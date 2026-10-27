"""Razorpay helpers for donations. Mirrors passes.payments: bookings.payments.create_order/refund expect a Booking,
everything else (client, signature checks, provider detection) is reused from bookings.payments.
"""
from bookings import payments as base

RAZORPAY = base.RAZORPAY
MOCK = base.MOCK
provider = base.provider
is_test_mode = base.is_test_mode
verify_checkout_signature = base.verify_checkout_signature
payment_method = base.payment_method
METHOD_MAP = base.METHOD_MAP


def create_order(donation):
    """Create (or reuse) the Razorpay order for this donation's amount."""
    amount = base.to_paise(donation.amount)
    if donation.gateway_order_id:
        existing = base._client().order.fetch(donation.gateway_order_id)
        if existing.get("amount") == amount and existing.get("status") != "paid":
            return existing
    rz_order = base._client().order.create({
        "amount": amount,
        "currency": "INR",
        "receipt": donation.reference,
        "notes": {"donation": donation.reference, "purpose": donation.purpose[:250]},
    })
    donation.gateway = RAZORPAY
    donation.gateway_order_id = rz_order["id"]
    donation.save(update_fields=["gateway", "gateway_order_id"])
    return rz_order


def refund(donation):
    return base._client().payment.refund(donation.payment_id, {
        "amount": base.to_paise(donation.amount),
        "speed": "normal",
        "notes": {"donation": donation.reference, "reason": "Donation refunded"},
    })
