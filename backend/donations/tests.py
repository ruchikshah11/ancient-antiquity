"""Donations: demo-gateway and Razorpay payment, 80G receipts, numbering, access control, admin CSV, fx-rates."""
import csv
import datetime
import io
import json
from decimal import Decimal
from unittest import mock

from django.core import mail
from django.test import Client, override_settings
from django.utils import timezone

from bookings.tests.factories import APITestCase, client_for, make_admin, make_museum, make_visitor
from bookings.tests.test_payments import KEY_SECRET, WEBHOOK_SECRET, WEBHOOK_URL, FakeRazorpay, sign
from donations import services
from donations.fx import parse_rates
from donations.models import Donation, financial_year
from donations.words import number_in_words, rupees_in_words

TRUST = dict(
    DONATION_TRUST_NAME="Ancient Antiquity Heritage Foundation", DONATION_TRUST_PAN="AAATA1234C",
    DONATION_80G_NUMBER="AAATA1234CF20241",
)


def payload(**extra):
    data = {"amount": "1000", "donor_name": "Asha Rao", "donor_email": "asha@example.com", "donor_phone": "9876543210"}
    data.update(extra)
    return data


def make_donation(**extra):
    fields = dict(amount=Decimal("500"), donor_name="Ravi", donor_email="ravi@example.com")
    fields.update(extra)
    return Donation.objects.create(**fields)


@override_settings(**TRUST)
class DonationFlowTests(APITestCase):
    def setUp(self):
        super().setUp()
        self.museum = make_museum()

    def create(self, client=None, **extra):
        return (client or client_for()).post("/api/donations/", payload(**extra), format="json")

    def test_guest_donates_with_demo_gateway_and_gets_80g_receipt(self):
        r = self.create(museum=self.museum.slug, wants_80g=True, donor_pan="abcde1234f", donor_address="1 MG Road, Pune")
        self.assertEqual(r.status_code, 201, r.data)
        ref, token = r.data["reference"], r.data["access_token"]
        self.assertEqual(r.data["status"], "pending")
        self.assertIsNone(r.data["receipt_number"])
        self.assertEqual(r.data["donor_pan"], "ABCDE1234F")
        self.assertEqual(r.data["museum_slug"], self.museum.slug)
        guest = client_for()
        r = guest.post(f"/api/donations/{ref}/payment-order/?token={token}")
        self.assertEqual(r.data, {"provider": "mock"})
        with self.captureOnCommitCallbacks(execute=True):
            r = guest.post(f"/api/donations/{ref}/pay/?token={token}", {"method": "upi"}, format="json")
        self.assertEqual(r.status_code, 200, r.data)
        self.assertEqual(r.data["status"], "paid")
        fy = financial_year(timezone.localdate())
        self.assertEqual(r.data["receipt_number"], f"AAHF/{fy}/000001")
        self.assertTrue(r.data["payment_id"].startswith("MOCK-"))
        self.assertTrue(r.data["is_80g_eligible"])
        self.assertEqual(r.data["amount_in_words"], "Rupees One Thousand Only")
        self.assertEqual(r.data["trust"]["registration_80g"], "AAATA1234CF20241")
        # Receipt emailed with the signed link
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn("AAHF/", mail.outbox[0].subject)
        self.assertIn(f"/donations/{ref}?token={token}", mail.outbox[0].body)
        self.assertIn("section 80G", mail.outbox[0].body)
        # Paying twice is refused
        r = guest.post(f"/api/donations/{ref}/pay/?token={token}", {"method": "upi"}, format="json")
        self.assertEqual(r.status_code, 400)

    def test_general_fund_without_80g(self):
        r = self.create()
        self.assertEqual(r.status_code, 201, r.data)
        self.assertIsNone(r.data["museum_slug"])
        self.assertEqual(r.data["purpose"], "General heritage fund")
        self.assertFalse(r.data["is_80g_eligible"])

    def test_logged_in_donation_is_linked_and_listed(self):
        visitor = make_visitor()
        client = client_for(visitor)
        r = self.create(client, donor_email=visitor.email)
        donation = Donation.objects.get(reference=r.data["reference"])
        self.assertEqual(donation.user, visitor)
        services.mark_paid(donation, "card")
        r = client.get("/api/donations/")
        self.assertEqual([d["reference"] for d in r.data], [donation.reference])
        self.assertEqual(client_for().get("/api/donations/").data, [])

    def test_minimum_amount(self):
        r = self.create(amount="99")
        self.assertEqual(r.status_code, 400)
        self.assertIn("amount", r.data)
        self.assertEqual(self.create(amount="100").status_code, 201)

    def test_pan_validation(self):
        for bad in ("ABCDE1234", "12345ABCDE", "ABCD12345F", "ABCDE1234FF"):
            r = self.create(donor_pan=bad)
            self.assertEqual(r.status_code, 400, bad)
            self.assertIn("donor_pan", r.data)
        r = self.create(donor_pan="abcde 1234 f")
        self.assertEqual(r.status_code, 201, r.data)
        self.assertEqual(r.data["donor_pan"], "ABCDE1234F")

    def test_80g_needs_pan_and_address(self):
        r = self.create(wants_80g=True)
        self.assertEqual(r.status_code, 400)
        self.assertIn("donor_pan", r.data)
        self.assertIn("donor_address", r.data)
        r = self.create(wants_80g=True, donor_pan="ABCDE1234F", donor_address="  ")
        self.assertIn("donor_address", r.data)

    def test_info_endpoint(self):
        r = client_for().get("/api/donations/info/")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.data["presets"], [500, 1000, 2500, 5000])
        self.assertEqual(r.data["trust"]["pan"], "AAATA1234C")
        self.assertEqual(r.data["provider"], "mock")

    def test_failed_then_paid(self):
        r = self.create()
        ref, token = r.data["reference"], r.data["access_token"]
        r = client_for().post(f"/api/donations/{ref}/failed/?token={token}")
        self.assertEqual(r.data["status"], "failed")
        r = client_for().post(f"/api/donations/{ref}/pay/?token={token}", {"method": "card"}, format="json")
        self.assertEqual(r.data["status"], "paid")


@override_settings(**TRUST)
class ReceiptNumberTests(APITestCase):
    def test_financial_year(self):
        self.assertEqual(financial_year(datetime.date(2026, 4, 1)), "2026-27")
        self.assertEqual(financial_year(datetime.date(2027, 3, 31)), "2026-27")
        self.assertEqual(financial_year(datetime.date(2026, 3, 31)), "2025-26")
        self.assertEqual(financial_year(datetime.date(2099, 12, 1)), "2099-00")

    def test_numbers_restart_each_financial_year(self):
        def pay_at(moment):
            d = make_donation()
            with mock.patch("django.utils.timezone.now", return_value=moment):
                return services.mark_paid(d, "upi").receipt_number

        tz = timezone.get_current_timezone()
        self.assertEqual(pay_at(datetime.datetime(2026, 3, 30, 12, tzinfo=tz)), "AAHF/2025-26/000001")
        self.assertEqual(pay_at(datetime.datetime(2026, 3, 31, 12, tzinfo=tz)), "AAHF/2025-26/000002")
        self.assertEqual(pay_at(datetime.datetime(2026, 4, 1, 9, tzinfo=tz)), "AAHF/2026-27/000001")
        self.assertEqual(pay_at(datetime.datetime(2026, 5, 1, 9, tzinfo=tz)), "AAHF/2026-27/000002")

    def test_pending_donations_have_no_number_and_paying_twice_keeps_it(self):
        d = make_donation()
        self.assertIsNone(d.receipt_number)
        first = services.mark_paid(d, "upi").receipt_number
        self.assertEqual(services.mark_paid(d, "upi").receipt_number, first)
        self.assertEqual(Donation.objects.exclude(receipt_number=None).count(), 1)

    @override_settings(DONATION_TRUST_NAME="Heritage Trust of India")
    def test_prefix_from_trust_name(self):
        self.assertTrue(services.mark_paid(make_donation(), "upi").receipt_number.startswith("HTI/"))

    def test_amount_in_words_indian_numbering(self):
        self.assertEqual(number_in_words(1_25_000), "One Lakh Twenty-Five Thousand")
        self.assertEqual(number_in_words(2_03_45_678), "Two Crore Three Lakh Forty-Five Thousand Six Hundred Seventy-Eight")
        self.assertEqual(number_in_words(100), "One Hundred")
        self.assertEqual(rupees_in_words(Decimal("1250.50")), "Rupees One Thousand Two Hundred Fifty and Fifty Paise Only")
        self.assertEqual(rupees_in_words(Decimal("10000000")), "Rupees One Crore Only")


@override_settings(**TRUST)
class ReceiptAccessTests(APITestCase):
    def setUp(self):
        super().setUp()
        self.owner = make_visitor(email="owner@example.com")
        self.donation = services.mark_paid(make_donation(donor_email="Owner@Example.com"), "upi")
        self.url = f"/api/donations/{self.donation.reference}/"

    def test_guest_needs_valid_token(self):
        self.assertEqual(client_for().get(self.url).status_code, 404)
        self.assertEqual(client_for().get(self.url, {"token": "forged"}).status_code, 404)
        token = services.access_token(self.donation)
        r = client_for().get(self.url, {"token": token})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.data["receipt_number"], self.donation.receipt_number)
        # A token for one donation does not open another
        other = make_donation()
        self.assertEqual(client_for().get(f"/api/donations/{other.reference}/", {"token": token}).status_code, 404)

    def test_owner_by_email_linked_user_and_admin(self):
        self.assertEqual(client_for(self.owner).get(self.url).status_code, 200)
        self.assertEqual(client_for(make_visitor()).get(self.url).status_code, 404)
        self.assertEqual(client_for(make_admin()).get(self.url).status_code, 200)
        linked_user = make_visitor()
        Donation.objects.filter(pk=self.donation.pk).update(user=linked_user)
        self.assertEqual(client_for(linked_user).get(self.url).status_code, 200)

    def test_stranger_cannot_pay_or_fail(self):
        d = make_donation()
        stranger = client_for(make_visitor())
        self.assertEqual(stranger.post(f"/api/donations/{d.reference}/pay/", {"method": "upi"}).status_code, 404)
        self.assertEqual(stranger.post(f"/api/donations/{d.reference}/failed/").status_code, 404)


@override_settings(RAZORPAY_KEY_ID="rzp_test_x", RAZORPAY_KEY_SECRET=KEY_SECRET, **TRUST)
class RazorpayDonationTests(APITestCase):
    def setUp(self):
        super().setUp()
        self.fake = FakeRazorpay(method="netbanking")
        patcher = mock.patch("bookings.payments._client", return_value=self.fake)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_checkout_signature_and_webhook_finalize(self):
        r = client_for().post("/api/donations/", payload(amount="2500"), format="json")
        ref, token = r.data["reference"], r.data["access_token"]
        r = client_for().post(f"/api/donations/{ref}/payment-order/?token={token}")
        self.assertEqual(r.status_code, 200, r.data)
        self.assertEqual(r.data["amount"], 250000)
        self.assertEqual(r.data["order_id"], "order_TEST1")
        bad = client_for().post(f"/api/donations/{ref}/pay/?token={token}", {
            "razorpay_order_id": "order_TEST1", "razorpay_payment_id": "pay_1", "razorpay_signature": "x"})
        self.assertEqual(bad.status_code, 400)
        r = client_for().post(f"/api/donations/{ref}/pay/?token={token}", {
            "razorpay_order_id": "order_TEST1", "razorpay_payment_id": "pay_1",
            "razorpay_signature": sign("order_TEST1|pay_1", KEY_SECRET)})
        self.assertEqual(r.status_code, 200, r.data)
        self.assertEqual(r.data["status"], "paid")
        self.assertEqual(r.data["payment_method"], "netbanking")
        number = r.data["receipt_number"]
        # The webhook arriving afterwards is a no-op
        donation = Donation.objects.get(reference=ref)
        services.finalize_gateway_payment(donation.pk, "pay_1")
        donation.refresh_from_db()
        self.assertEqual(donation.receipt_number, number)

    @override_settings(RAZORPAY_WEBHOOK_SECRET=WEBHOOK_SECRET)
    def test_razorpay_webhook_endpoint_confirms_donation(self):
        d = make_donation(gateway_order_id="order_HOOK")
        body = json.dumps({"event": "payment.captured", "payload": {"payment": {"entity": {
            "id": "pay_HOOK", "order_id": "order_HOOK", "method": "upi"}}}})
        r = Client().post(WEBHOOK_URL, data=body, content_type="application/json",
                          headers={"X-Razorpay-Signature": sign(body, WEBHOOK_SECRET)})
        self.assertEqual(r.status_code, 200)
        d.refresh_from_db()
        self.assertEqual((d.status, d.payment_id), ("paid", "pay_HOOK"))
        self.assertTrue(d.receipt_number)

    def test_webhook_only_payment(self):
        d = make_donation(gateway_order_id="order_W")
        services.finalize_gateway_payment(d.pk, "pay_W")
        d.refresh_from_db()
        self.assertEqual((d.status, d.gateway, d.payment_id), ("paid", "razorpay", "pay_W"))
        self.assertTrue(d.receipt_number)

    def test_admin_refund_through_razorpay(self):
        d = make_donation()
        services.finalize_gateway_payment(d.pk, "pay_R")
        r = client_for(make_admin()).post(f"/api/admin/donations/{d.reference}/refund/")
        self.assertEqual(r.status_code, 200, r.data)
        self.assertEqual(r.data["status"], "refunded")
        self.fake.payment.refund.assert_called_once()


@override_settings(**TRUST)
class AdminDonationTests(APITestCase):
    def setUp(self):
        super().setUp()
        self.admin = client_for(make_admin())
        self.museum = make_museum()
        self.a = services.mark_paid(make_donation(
            amount=Decimal("5000"), museum=self.museum, wants_80g=True, donor_pan="ABCDE1234F",
            donor_address="12, Park Street, Kolkata", donor_name="Meera, Sen"), "upi")
        self.b = services.mark_paid(make_donation(amount=Decimal("1000")), "card")
        self.pending = make_donation(amount=Decimal("700"))

    def test_only_admins(self):
        self.assertEqual(client_for(make_visitor()).get("/api/admin/donations/").status_code, 403)
        self.assertEqual(client_for().get("/api/admin/donations/export/").status_code, 401)

    def test_list_filters_and_totals(self):
        r = self.admin.get("/api/admin/donations/")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.data["count"], 3)
        self.assertEqual(r.data["totals"]["paid_amount"], "6000.00")
        self.assertEqual(r.data["totals"]["paid_80g_amount"], "5000.00")
        self.assertEqual(r.data["totals"]["paid_count"], 2)
        r = self.admin.get("/api/admin/donations/", {"museum": self.museum.slug})
        self.assertEqual([d["reference"] for d in r.data["results"]], [self.a.reference])
        r = self.admin.get("/api/admin/donations/", {"museum": "general", "status": "paid"})
        self.assertEqual([d["reference"] for d in r.data["results"]], [self.b.reference])
        r = self.admin.get("/api/admin/donations/", {"wants_80g": "false"})
        self.assertEqual(r.data["count"], 2)
        today = timezone.localdate()
        r = self.admin.get("/api/admin/donations/", {"date_from": today, "date_to": today})
        self.assertEqual(r.data["count"], 3)
        r = self.admin.get("/api/admin/donations/", {"date_from": today + datetime.timedelta(days=1)})
        self.assertEqual(r.data["count"], 0)
        r = self.admin.get("/api/admin/donations/", {"search": "ABCDE1234F"})
        self.assertEqual(r.data["count"], 1)

    def test_form_10bd_csv(self):
        r = self.admin.get("/api/admin/donations/export/")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r["Content-Type"], "text/csv; charset=utf-8")
        rows = list(csv.reader(io.StringIO(r.content.decode("utf-8-sig"))))
        header, body = rows[0], rows[1:]
        for col in ("Receipt number", "Date of donation", "Name of donor", "Address of donor",
                    "Unique identification number", "Mode of receipt", "Amount of donation (INR)"):
            self.assertIn(col, header)
        self.assertEqual(len(body), 2)  # pending donation left out
        row = dict(zip(header, body[0]))
        self.assertEqual(row["Receipt number"], self.a.receipt_number)
        self.assertEqual(row["Name of donor"], "Meera, Sen")  # commas quoted correctly
        self.assertEqual(row["Address of donor"], "12, Park Street, Kolkata")
        self.assertEqual(row["Unique identification number"], "ABCDE1234F")
        self.assertEqual(row["ID code"], "Permanent Account Number")
        self.assertEqual(row["Section code"], "Section 80G")
        self.assertEqual(row["Amount of donation (INR)"], "5000.00")
        self.assertEqual(row["Date of donation"], f"{timezone.localdate():%d-%m-%Y}")
        r = self.admin.get("/api/admin/donations/export/", {"wants_80g": "true"})
        self.assertEqual(len(list(csv.reader(io.StringIO(r.content.decode("utf-8-sig"))))) - 1, 1)

    def test_demo_refund(self):
        r = self.admin.post(f"/api/admin/donations/{self.b.reference}/refund/")
        self.assertEqual(r.data["status"], "refunded")
        self.assertEqual(self.admin.post(f"/api/admin/donations/{self.pending.reference}/refund/").status_code, 400)


class FxRatesTests(APITestCase):
    @override_settings(FX_RATES="USD=0.012,EUR=0.011,GBP=0.0095")
    def test_rates_with_aed_default(self):
        r = client_for().get("/api/fx-rates/")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.data["base"], "INR")
        self.assertEqual(r.data["rates"]["USD"], 0.012)
        self.assertEqual(r.data["rates"]["GBP"], 0.0095)
        self.assertIn("AED", r.data["rates"])
        self.assertTrue(r.data["updated"])

    @override_settings(FX_RATES="usd=0.02, JPY=1.8, bad, INR=1, XYZ=abc, AED=0.05")
    def test_settings_override_and_bad_entries_skipped(self):
        r = client_for().get("/api/fx-rates/")
        self.assertEqual(r.data["rates"]["USD"], 0.02)
        self.assertEqual(r.data["rates"]["JPY"], 1.8)
        self.assertEqual(r.data["rates"]["AED"], 0.05)
        self.assertNotIn("INR", r.data["rates"])
        self.assertNotIn("XYZ", r.data["rates"])

    def test_parse_rates(self):
        self.assertEqual(parse_rates(""), {})
        self.assertEqual(parse_rates("EUR=0.5,EUR=-1"), {"EUR": 0.5})
