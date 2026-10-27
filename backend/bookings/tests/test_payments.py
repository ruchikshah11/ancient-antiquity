"""Razorpay flow with a fake client: checkout signature, webhooks, idempotency, auto refunds."""
import datetime
import hashlib
import hmac
import json
import unittest
from decimal import Decimal
from unittest import mock

from django.conf import settings
from django.test import Client, override_settings

from bookings import services
from bookings.models import Booking
from bookings.tests.factories import (
    APITestCase, age_booking, book, client_for, make_museum, make_visitor,
)

KEY_SECRET = "test-key-secret"
WEBHOOK_SECRET = "test-webhook-secret"
WEBHOOK_URL = "/api/payments/razorpay/webhook/"


def sign(message, secret):
    return hmac.new(secret.encode(), message.encode() if isinstance(message, str) else message, hashlib.sha256).hexdigest()


class FakeRazorpay:
    """Stands in for razorpay.Client: records calls, returns canned objects."""

    def __init__(self, method="card", refund_status="processed"):
        self.order = mock.Mock()
        self.order.create.side_effect = lambda data: {"id": "order_TEST1", "amount": data["amount"], "currency": "INR", "status": "created"}
        self.order.fetch.return_value = {"id": "order_TEST1", "amount": 0, "status": "created"}
        self.payment = mock.Mock()
        self.payment.fetch.return_value = {"method": method}
        self.payment.refund.return_value = {"id": "rfnd_TEST1", "status": refund_status}


@override_settings(RAZORPAY_KEY_ID="rzp_test_x", RAZORPAY_KEY_SECRET=KEY_SECRET, RAZORPAY_WEBHOOK_SECRET=WEBHOOK_SECRET)
class RazorpayTests(APITestCase):
    def setUp(self):
        super().setUp()
        self.fake = FakeRazorpay()
        patcher = mock.patch("bookings.payments._client", return_value=self.fake)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.museum = make_museum(slots=[(datetime.time(10), datetime.time(11), 3)])
        self.visitor = make_visitor()
        self.client = client_for(self.visitor)
        self.booking = book(self.visitor, self.museum, qty=2)  # 100.00

    # -- helpers
    def start_checkout(self, booking=None):
        booking = booking or self.booking
        r = self.client.post(f"/api/bookings/{booking.reference}/payment-order/")
        self.assertEqual(r.status_code, 200, r.data)
        booking.refresh_from_db()
        return r

    def pay(self, order_id="order_TEST1", payment_id="pay_TEST1", signature=None, booking=None):
        booking = booking or self.booking
        if signature is None:
            signature = sign(f"{order_id}|{payment_id}", KEY_SECRET)
        return self.client.post(f"/api/bookings/{booking.reference}/pay/", {
            "razorpay_order_id": order_id, "razorpay_payment_id": payment_id, "razorpay_signature": signature,
        })

    def webhook(self, payload, signature=None):
        body = json.dumps(payload)
        if signature is None:
            signature = sign(body, WEBHOOK_SECRET)
        return Client().post(WEBHOOK_URL, data=body, content_type="application/json",
                             headers={"X-Razorpay-Signature": signature})

    @staticmethod
    def captured(order_id="order_TEST1", payment_id="pay_TEST1", method="netbanking"):
        return {"event": "payment.captured", "payload": {"payment": {"entity": {
            "id": payment_id, "order_id": order_id, "method": method}}}}

    # -- tests
    def test_payment_order(self):
        r = self.start_checkout()
        self.assertEqual(r.data["provider"], "razorpay")
        self.assertTrue(r.data["test_mode"])
        self.assertEqual(r.data["order_id"], "order_TEST1")
        self.assertEqual(r.data["amount"], 10000)  # paise
        self.assertEqual(self.booking.gateway_order_id, "order_TEST1")
        self.assertEqual(client_for().get("/api/payments/config/").data["provider"], "razorpay")

    def test_forged_signature_rejected(self):
        self.start_checkout()
        r = self.pay(signature="0" * 64)
        self.assertEqual(r.status_code, 400)
        self.booking.refresh_from_db()
        self.assertEqual(self.booking.status, Booking.Status.PENDING)

    def test_order_mismatch_rejected(self):
        self.start_checkout()
        r = self.pay(order_id="order_SOMEONE_ELSE")  # correctly signed, but for another order
        self.assertEqual(r.status_code, 400)
        self.assertIn("does not belong", str(r.data))

    def test_pay_without_order_rejected(self):
        self.assertEqual(self.pay().status_code, 400)

    def test_valid_signature_confirms_and_stores_method(self):
        self.start_checkout()
        r = self.pay()
        self.assertEqual(r.status_code, 200, r.data)
        self.booking.refresh_from_db()
        self.assertEqual(self.booking.status, Booking.Status.CONFIRMED)
        self.assertEqual(self.booking.payment_method, "card")
        self.assertEqual(self.booking.payment_id, "pay_TEST1")
        self.assertEqual(self.booking.gateway, "razorpay")
        self.fake.payment.fetch.assert_called_once_with("pay_TEST1")

    def test_webhook_bad_signature(self):
        self.start_checkout()
        self.assertEqual(self.webhook(self.captured(), signature="forged").status_code, 400)
        self.assertEqual(self.webhook(self.captured(), signature="").status_code, 400)
        self.booking.refresh_from_db()
        self.assertEqual(self.booking.status, Booking.Status.PENDING)

    def test_webhook_alone_confirms(self):
        self.start_checkout()
        r = self.webhook(self.captured())
        self.assertEqual(r.status_code, 200)
        self.booking.refresh_from_db()
        self.assertEqual(self.booking.status, Booking.Status.CONFIRMED)
        self.assertEqual(self.booking.payment_method, "netbanking")

    def test_duplicate_capture_is_idempotent(self):
        self.start_checkout()
        self.pay()
        self.booking.refresh_from_db()
        paid_at = self.booking.paid_at
        for _ in range(2):
            self.assertEqual(self.webhook(self.captured(payment_id="pay_TEST1")).status_code, 200)
        self.booking.refresh_from_db()
        self.assertEqual((self.booking.status, self.booking.paid_at, self.booking.payment_method),
                         (Booking.Status.CONFIRMED, paid_at, "card"))
        self.fake.payment.refund.assert_not_called()

    def test_expired_hold_with_free_seats_still_confirms(self):
        self.start_checkout()
        age_booking(self.booking, settings.BOOKING_HOLD_MINUTES + 5)
        r = self.pay()
        self.assertEqual(r.status_code, 200, r.data)
        self.assertEqual(r.data["status"], "confirmed")

    def _pay_after_slot_filled(self):
        self.start_checkout()
        age_booking(self.booking, settings.BOOKING_HOLD_MINUTES + 5)
        book(make_visitor(), self.museum, qty=3, confirm=True)  # someone else took the whole slot

    def test_expired_hold_and_full_slot_refunds_automatically(self):
        self._pay_after_slot_filled()
        r = self.pay()
        self.assertEqual(r.status_code, 400)
        self.assertIn("refunded automatically", str(r.data))
        self.booking.refresh_from_db()
        self.assertNotEqual(self.booking.status, Booking.Status.CONFIRMED)
        self.fake.payment.refund.assert_called_once()
        args = self.fake.payment.refund.call_args[0]
        self.assertEqual((args[0], args[1]["amount"]), ("pay_TEST1", 10000))

    # BUG: finalize_gateway_payment() is @transaction.atomic and raises ValidationError *after* issue_refund()
    # has called Razorpay and saved refund_id/refund_amount/refund_status/payment_id. The exception rolls the
    # whole block back, so the money is refunded at the gateway but the booking records no refund (and keeps
    # no payment_id). The later refund.processed/failed webhook then matches no booking (refund_id is empty).
    # Fix idea: do the refund bookkeeping and return a flag instead of raising inside the atomic block (or
    # raise after the transaction commits).
    def test_auto_refund_is_recorded_on_booking(self):
        self._pay_after_slot_filled()
        self.pay()
        self.booking.refresh_from_db()
        self.assertEqual(self.booking.status, Booking.Status.EXPIRED)
        self.assertEqual(self.booking.payment_id, "pay_TEST1")
        self.assertEqual(self.booking.refund_id, "rfnd_TEST1")
        self.assertEqual(self.booking.refund_amount, Decimal("100.00"))
        self.assertEqual(self.booking.refund_status, Booking.RefundStatus.PROCESSED)
    def test_auto_refund_via_webhook_is_recorded_on_booking(self):
        self._pay_after_slot_filled()
        self.assertEqual(self.webhook(self.captured()).status_code, 200)
        self.fake.payment.refund.assert_called_once()
        self.booking.refresh_from_db()
        self.assertEqual((self.booking.status, self.booking.refund_amount), (Booking.Status.EXPIRED, Decimal("100.00")))

    def test_cancel_paid_booking_refunds_through_gateway_and_webhook_updates_status(self):
        self.fake.payment.refund.return_value = {"id": "rfnd_TEST1", "status": "pending"}
        self.start_checkout()
        self.pay()
        r = self.client.post(f"/api/bookings/{self.booking.reference}/cancel/")
        self.assertEqual(r.status_code, 200, r.data)
        self.assertEqual((r.data["refund_status"], r.data["refund_id"]), ("pending", "rfnd_TEST1"))

        refund_event = {"event": "refund.processed", "payload": {"refund": {"entity": {"id": "rfnd_TEST1"}}}}
        self.assertEqual(self.webhook(refund_event).status_code, 200)
        self.booking.refresh_from_db()
        self.assertEqual(self.booking.refund_status, Booking.RefundStatus.PROCESSED)

        refund_event["event"] = "refund.failed"
        self.webhook(refund_event)
        self.booking.refresh_from_db()
        self.assertEqual(self.booking.refund_status, Booking.RefundStatus.FAILED)

    def test_gateway_refund_failure_keeps_booking(self):
        self.start_checkout()
        self.pay()
        self.fake.payment.refund.side_effect = RuntimeError("gateway down")
        r = self.client.post(f"/api/bookings/{self.booking.reference}/cancel/")
        self.assertEqual(r.status_code, 400)
        self.booking.refresh_from_db()
        self.assertEqual(self.booking.status, Booking.Status.CONFIRMED)
        self.assertEqual(self.booking.refund_amount, Decimal("0"))

    def test_finalize_is_idempotent_at_service_level(self):
        self.start_checkout()
        first = services.finalize_gateway_payment(self.booking.pk, "pay_A", "upi")
        second = services.finalize_gateway_payment(self.booking.pk, "pay_B", "card")
        self.assertEqual((first.payment_id, second.payment_id), ("pay_A", "pay_A"))


class WebhookWithoutSecretTests(APITestCase):
    @override_settings(RAZORPAY_WEBHOOK_SECRET="")
    def test_webhook_rejected_when_secret_not_configured(self):
        body = json.dumps({"event": "payment.captured"})
        r = Client().post(WEBHOOK_URL, data=body, content_type="application/json",
                          headers={"X-Razorpay-Signature": sign(body, "")})
        self.assertEqual(r.status_code, 400)
