"""Razorpay helpers for Heritage Card purchases. Mirrors passes.payments: everything except the order and the
refund (which expect a Booking there) is reused from bookings.payments.
"""
from bookings import payments as base

RAZORPAY = base.RAZORPAY
MOCK = base.MOCK
provider = base.provider
is_test_mode = base.is_test_mode
verify_checkout_signature = base.verify_checkout_signature
payment_method = base.payment_method
METHOD_MAP = base.METHOD_MAP


def create_order(membership):
    """Create (or reuse) the Razorpay order for this membership's amount."""
    amount = base.to_paise(membership.total_amount)
    if membership.gateway_order_id:
        existing = base._client().order.fetch(membership.gateway_order_id)
        if existing.get("amount") == amount and existing.get("status") != "paid":
            return existing
    rz_order = base._client().order.create({
        "amount": amount,
        "currency": "INR",
        "receipt": membership.card_number,
        "notes": {"membership": membership.card_number, "plan": membership.plan_name[:250]},
    })
    membership.gateway = RAZORPAY
    membership.gateway_order_id = rz_order["id"]
    membership.save(update_fields=["gateway", "gateway_order_id"])
    return rz_order


def refund(membership, amount):
    return base._client().payment.refund(membership.payment_id, {
        "amount": base.to_paise(amount),
        "speed": "normal",
        "notes": {"membership": membership.card_number, "reason": "Membership cancelled"},
    })
