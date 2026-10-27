"""Booking emails sent from model signals (after commit) and the resend endpoint."""
import unittest
from email.mime.base import MIMEBase
from unittest import mock

from django.core import mail
from django.test import override_settings

from bookings import services
from bookings.models import Booking
from bookings.tests.factories import (
    ALL_DAY, APITestCase, book, client_for, make_museum, make_staff, make_visitor, ticket,
)
from notifications.models import NotificationLog
from notifications.services import QR_CID
from notifications.views import RESEND_LIMIT_PER_HOUR


def qr_parts(message):
    return [a for a in message.attachments if isinstance(a, MIMEBase) and a.get("Content-ID") == f"<{QR_CID}>"]


@override_settings(RAZORPAY_KEY_ID="", RAZORPAY_KEY_SECRET="", SMS_PROVIDER="console")
class BookingEmailTests(APITestCase):
    def setUp(self):
        super().setUp()
        self.museum = make_museum("Salar Jung Museum")
        self.visitor = make_visitor()
        self.client = client_for(self.visitor)

    def test_confirmation_email_on_payment(self):
        booking = book(self.visitor, self.museum, qty=2)
        self.assertEqual(len(mail.outbox), 0)  # nothing for a pending booking
        with self.captureOnCommitCallbacks(execute=True):
            r = self.client.post(f"/api/bookings/{booking.reference}/pay/", {"method": "upi"})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(len(mail.outbox), 1)
        msg = mail.outbox[0]
        self.assertEqual(msg.to, [self.visitor.email])
        self.assertIn(booking.reference, msg.subject)
        self.assertIn(booking.reference, msg.body)
        self.assertIn("CONFIRMED", msg.body)
        self.assertEqual(len(qr_parts(msg)), 1, "ticket QR must be attached inline")
        self.assertEqual(msg.alternatives[0][1], "text/html")
        self.assertTrue(NotificationLog.objects.filter(booking=booking, kind="confirmed", channel="email", status="sent").exists())
        self.assertTrue(NotificationLog.objects.filter(booking=booking, kind="confirmed", channel="sms").exists())

    def test_cancellation_email_mentions_refund_and_has_no_qr(self):
        booking = book(self.visitor, self.museum, qty=2, confirm=True)
        with self.captureOnCommitCallbacks(execute=True):
            self.client.post(f"/api/bookings/{booking.reference}/cancel/")
        self.assertEqual(len(mail.outbox), 1)
        msg = mail.outbox[0]
        self.assertIn("cancelled", msg.subject.lower())
        self.assertIn("Refund: Rs 100.00", msg.body)
        self.assertEqual(qr_parts(msg), [])

    def test_cancellation_without_refund_says_so(self):
        booking = book(self.visitor, self.museum)  # unpaid
        with self.captureOnCommitCallbacks(execute=True):
            self.client.post(f"/api/bookings/{booking.reference}/cancel/")
        self.assertIn("No refund applies", mail.outbox[0].body)

    def test_counter_sale_without_email_is_skipped(self):
        museum = make_museum(slots=[(*ALL_DAY, 50)])
        staff = make_staff(museum)
        with self.captureOnCommitCallbacks(execute=True):
            r = client_for(staff).post("/api/bookings/counter/", {
                "museum": museum.slug, "slot": museum.slots.first().id, "payment_method": "cash",
                "items": [{"ticket_type": ticket(museum).id, "quantity": 1}],
            }, format="json")
        self.assertEqual(r.status_code, 201, r.data)
        self.assertEqual(len(mail.outbox), 0)
        self.assertEqual(NotificationLog.objects.get(kind="confirmed").status, NotificationLog.Status.SKIPPED)

    def test_email_failure_does_not_break_payment(self):
        booking = book(self.visitor, self.museum)
        with mock.patch("django.core.mail.EmailMultiAlternatives.send", side_effect=OSError("SMTP down")):
            with self.captureOnCommitCallbacks(execute=True):
                r = self.client.post(f"/api/bookings/{booking.reference}/pay/", {"method": "upi"})
        self.assertEqual(r.status_code, 200)
        booking.refresh_from_db()
        self.assertEqual(booking.status, Booking.Status.CONFIRMED)
        self.assertEqual(NotificationLog.objects.get(kind="confirmed", channel="email").status, NotificationLog.Status.FAILED)

    def test_no_email_if_transaction_never_commits(self):
        booking = book(self.visitor, self.museum)
        services.confirm_payment(booking, Booking.PaymentMethod.UPI)  # on_commit callbacks are not run here
        self.assertEqual(len(mail.outbox), 0)


class ResendTests(APITestCase):
    def setUp(self):
        super().setUp()
        self.museum = make_museum()
        self.visitor = make_visitor()
        self.booking = book(self.visitor, self.museum, confirm=True)
        self.url = f"/api/notifications/bookings/{self.booking.reference}/resend/"

    def test_owner_can_resend_until_rate_limit(self):
        client = client_for(self.visitor)
        for _ in range(RESEND_LIMIT_PER_HOUR):
            self.assertEqual(client.post(self.url).status_code, 200)
        self.assertEqual(len(mail.outbox), 3)
        self.assertEqual(len(qr_parts(mail.outbox[0])), 1)
        r = client.post(self.url)
        self.assertEqual(r.status_code, 429)
        self.assertEqual(len(mail.outbox), 3)

    def test_permissions(self):
        self.assertEqual(client_for().post(self.url).status_code, 401)
        self.assertEqual(client_for(make_visitor()).post(self.url).status_code, 403)
        self.assertEqual(client_for(make_staff(self.museum)).post(self.url).status_code, 200)

    # BUG (authorization gap): the resend view only checks request.user.is_panel_user, so staff of ANY place -
    # even one with no assigned places - can trigger ticket emails (with the visitor's QR code) for bookings at
    # places they are not assigned to. Every other panel endpoint enforces assignment (ensure_museum_access).
    def test_staff_of_another_place_cannot_resend(self):
        self.assertEqual(client_for(make_staff(make_museum())).post(self.url).status_code, 403)

    def test_only_confirmed_bookings(self):
        pending = book(self.visitor, self.museum)
        r = client_for(self.visitor).post(f"/api/notifications/bookings/{pending.reference}/resend/")
        self.assertEqual(r.status_code, 400)
        self.assertEqual(len(mail.outbox), 0)
