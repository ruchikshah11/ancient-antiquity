"""Razorpay helpers for pass orders. bookings.payments.create_order/refund expect a Booking, so these mirror them
for PassOrder and reuse everything else (client, signature checks, provider detection) from bookings.payments.
"""
from bookings import payments as base

RAZORPAY = base.RAZORPAY
MOCK = base.MOCK
provider = base.provider
is_test_mode = base.is_test_mode
verify_checkout_signature = base.verify_checkout_signature
payment_method = base.payment_method
METHOD_MAP = base.METHOD_MAP


def create_order(order):
    """Create (or reuse) the Razorpay order for this pass order's amount."""
    amount = base.to_paise(order.total_amount)
    if order.gateway_order_id:
        existing = base._client().order.fetch(order.gateway_order_id)
        if existing.get("amount") == amount and existing.get("status") != "paid":
            return existing
    rz_order = base._client().order.create({
        "amount": amount,
        "currency": "INR",
        "receipt": order.reference,
        "notes": {"pass_order": order.reference, "pass": order.pass_name[:250]},
    })
    order.gateway = RAZORPAY
    order.gateway_order_id = rz_order["id"]
    order.save(update_fields=["gateway", "gateway_order_id"])
    return rz_order


def refund(order, amount):
    return base._client().payment.refund(order.payment_id, {
        "amount": base.to_paise(amount),
        "speed": "normal",
        "notes": {"pass_order": order.reference, "reason": "Visitor cancelled"},
    })
