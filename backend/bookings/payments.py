"""Payment gateway: Razorpay when keys are configured in .env, otherwise the built-in demo gateway.

Flow (Razorpay Standard Checkout):
1. create_order(): server creates a Razorpay order for the booking amount (in paise).
2. The browser opens Razorpay Checkout with that order id; the visitor pays by UPI/card/netbanking/wallet.
3. verify_checkout_signature(): server checks HMAC-SHA256(order_id|payment_id, key_secret) before confirming,
   so a payment can't be faked from the browser.
4. The payment.captured webhook confirms the booking too, in case the browser closed right after paying.
Refunds go back through the same payment via refund().
"""
import hashlib
import hmac
from decimal import Decimal

from django.conf import settings

RAZORPAY = "razorpay"
MOCK = "mock"

# Razorpay payment.method -> our Booking.PaymentMethod values
METHOD_MAP = {"upi": "upi", "card": "card", "netbanking": "netbanking", "wallet": "wallet", "emi": "card", "paylater": "wallet"}


def provider():
    return RAZORPAY if settings.RAZORPAY_KEY_ID and settings.RAZORPAY_KEY_SECRET else MOCK


def is_test_mode():
    return settings.RAZORPAY_KEY_ID.startswith("rzp_test_")


def _client():
    import razorpay

    client = razorpay.Client(auth=(settings.RAZORPAY_KEY_ID, settings.RAZORPAY_KEY_SECRET))
    client.set_app_details({"title": "Ancient Antiquity", "version": "1.0"})
    return client


def to_paise(amount):
    return int((Decimal(amount) * 100).quantize(Decimal(1)))


def create_order(booking):
    """Create (or reuse) the Razorpay order for this booking's current amount."""
    amount = to_paise(booking.total_amount)
    if booking.gateway_order_id:
        existing = _client().order.fetch(booking.gateway_order_id)
        if existing.get("amount") == amount and existing.get("status") != "paid":
            return existing
    order = _client().order.create({
        "amount": amount,
        "currency": "INR",
        "receipt": booking.reference,
        "notes": {"booking": booking.reference, "place": booking.museum.name[:250]},
    })
    booking.gateway = RAZORPAY
    booking.gateway_order_id = order["id"]
    booking.save(update_fields=["gateway", "gateway_order_id"])
    return order


def _hmac(secret, message):
    return hmac.new(secret.encode(), message, hashlib.sha256).hexdigest()


def verify_checkout_signature(order_id, payment_id, signature):
    expected = _hmac(settings.RAZORPAY_KEY_SECRET, f"{order_id}|{payment_id}".encode())
    return hmac.compare_digest(expected, signature or "")


def verify_webhook_signature(body, signature):
    if not settings.RAZORPAY_WEBHOOK_SECRET:
        return False
    return hmac.compare_digest(_hmac(settings.RAZORPAY_WEBHOOK_SECRET, body), signature or "")


def payment_method(payment_id):
    """Ask Razorpay how the visitor paid (UPI, card...). Falls back to UPI if the lookup fails."""
    try:
        method = _client().payment.fetch(payment_id).get("method", "")
    except Exception:  # network/API hiccup: the payment itself is already verified
        method = ""
    return METHOD_MAP.get(method, "upi")


def refund(booking, amount):
    """Refund `amount` (rupees) of the booking's payment. Returns the Razorpay refund object."""
    return _client().payment.refund(booking.payment_id, {
        "amount": to_paise(amount),
        "speed": "normal",
        "notes": {"booking": booking.reference, "reason": "Visitor cancelled"},
    })
