"""Add-ons and the Heritage Card discount inside the booking money flow: payment order, refunds, invoice, reports."""
import datetime
from decimal import Decimal
from unittest import mock

from django.test import override_settings

from addons.tests import make_addon
from addons.models import AddOn
from bookings import services
from bookings.models import Booking
from bookings.tests.factories import APITestCase, book, client_for, make_admin, make_museum, make_visitor
from bookings.tests.test_payments import KEY_SECRET, FakeRazorpay
from memberships.tests import book_mixed, make_member, make_plan


class AddOnMoneyTests(APITestCase):
    def setUp(self):
        super().setUp()
        self.museum = make_museum()
        self.audio = make_addon(self.museum)  # ₹150 per person
        self.camera = make_addon(self.museum, "Camera permit", AddOn.Kind.CAMERA, "50", AddOn.Per.BOOKING)
        self.visitor = make_visitor()
        self.client = client_for(self.visitor)
        self.booking = book(self.visitor, self.museum, qty=2)  # ₹100 of tickets
        services.set_booking_addons(self.booking, [
            {"addon": self.audio.id, "quantity": 2}, {"addon": self.camera.id, "quantity": 1},
        ])
        self.booking.refresh_from_db()

    def test_demo_payment_and_refund_include_addons(self):
        self.assertEqual(self.booking.total_amount, Decimal("450"))
        r = self.client.post(f"/api/bookings/{self.booking.reference}/pay/", {"method": "upi"})
        self.assertEqual(r.data["status"], "confirmed")
        self.assertEqual(Decimal(r.data["refundable_amount"]), Decimal("450"))
        r = self.client.post(f"/api/bookings/{self.booking.reference}/cancel/")
        self.assertEqual(Decimal(r.data["refund_amount"]), Decimal("450"))
        self.assertEqual(r.data["refund_status"], "processed")

    def test_late_cancel_refunds_nothing_including_addons(self):
        services.confirm_payment(self.booking, Booking.PaymentMethod.UPI)
        Booking.objects.filter(pk=self.booking.pk).update(visit_date=datetime.date.today())
        self.booking.refresh_from_db()
        with mock.patch.object(Booking, "slot_starts_at", new=self.booking.created_at + datetime.timedelta(hours=1)):
            self.assertEqual(self.booking.refundable_amount, 0)

    @override_settings(RAZORPAY_KEY_ID="rzp_test_x", RAZORPAY_KEY_SECRET=KEY_SECRET)
    def test_razorpay_order_amount_includes_addons(self):
        fake = FakeRazorpay()
        with mock.patch("bookings.payments._client", return_value=fake):
            r = self.client.post(f"/api/bookings/{self.booking.reference}/payment-order/")
        self.assertEqual(r.status_code, 200, r.data)
        self.assertEqual(r.data["amount"], 45000)

    def test_invoice_lists_addons_as_separate_lines(self):
        services.confirm_payment(self.booking, Booking.PaymentMethod.UPI)
        r = self.client.get(f"/api/bookings/{self.booking.reference}/invoice/")
        self.assertEqual(r.status_code, 200, r.data)
        lines = [(i["description"], i["quantity"], i["amount"], i["kind"]) for i in r.data["items"]]
        self.assertEqual(lines, [
            ("Indian adult", 2, Decimal("100.00"), "ticket"),
            ("Audio guide", 2, Decimal("300.00"), "addon"),
            ("Camera permit", 1, Decimal("50.00"), "addon"),
        ])
        self.assertEqual(r.data["subtotal"], Decimal("450.00"))
        self.assertEqual(r.data["total"], Decimal("450.00"))

    def test_reports_revenue_includes_addons(self):
        services.confirm_payment(self.booking, Booking.PaymentMethod.UPI)
        r = client_for(make_admin()).get("/api/admin/reports/summary/")
        self.assertEqual(r.status_code, 200, r.data)
        self.assertEqual(r.data["totals"]["revenue"], Decimal("450.00"))
        self.assertEqual(r.data["totals"]["addons"], Decimal("350.00"))


class MembershipMoneyTests(APITestCase):
    def setUp(self):
        super().setUp()
        self.museum = make_museum()
        self.visitor = make_visitor()
        self.client = client_for(self.visitor)
        self.card = make_member(self.visitor, make_plan())  # 20% off 1 ticket

    def test_invoice_shows_heritage_card_discount(self):
        booking = book_mixed(self.visitor, self.museum, adults=1, foreign=1)  # 650 - 120
        services.set_booking_addons(booking, [{"addon": make_addon(self.museum).id, "quantity": 1}])
        services.confirm_payment(booking, Booking.PaymentMethod.CARD)
        r = self.client.get(f"/api/bookings/{booking.reference}/invoice/")
        self.assertEqual(r.data["membership_discount"], Decimal("120.00"))
        self.assertEqual(r.data["membership_card"], self.card.card_number)
        self.assertEqual(r.data["subtotal"], Decimal("800.00"))  # tickets 650 + audio guide 150
        self.assertEqual(r.data["total"], Decimal("680.00"))

    def test_ticket_api_has_discount_and_refund_uses_paid_amount(self):
        booking = book_mixed(self.visitor, self.museum, adults=0, foreign=1)
        services.confirm_payment(booking, Booking.PaymentMethod.CARD)
        r = self.client.get(f"/api/bookings/{booking.reference}/")
        self.assertEqual(Decimal(r.data["membership_discount"]), Decimal("120"))
        self.assertEqual(Decimal(r.data["total_amount"]), Decimal("480"))
        r = self.client.post(f"/api/bookings/{booking.reference}/cancel/")
        self.assertEqual(Decimal(r.data["refund_amount"]), Decimal("480"))
