"""Promo codes and gift vouchers: validation, amounts, voucher balance and its release."""
import datetime
from decimal import Decimal

from django.core import mail
from django.utils import timezone

from bookings import services as booking_services
from bookings.models import Booking
from bookings.tests.factories import (
    APITestCase, age_booking, book, client_for, make_admin, make_museum, make_staff, make_visitor,
)
from museums.models import Museum

from .models import GiftVoucher, PromoCode


def apply(user, booking, code):
    return client_for(user).post(f"/api/bookings/{booking.reference}/apply-code/", {"code": code}, format="json")


class PromoCodeTests(APITestCase):
    def setUp(self):
        super().setUp()
        self.museum = make_museum()
        self.visitor = make_visitor()
        self.booking = book(self.visitor, self.museum, qty=4)  # 4 x 50 = 200

    def test_percent_code_case_insensitive_with_cap(self):
        PromoCode.objects.create(code="heritage20", value=20, max_discount=30)
        res = apply(self.visitor, self.booking, "  Heritage20 ")
        self.assertEqual(res.status_code, 200, res.data)
        self.assertEqual(Decimal(res.data["promo_discount"]), Decimal("30"))
        self.assertEqual(Decimal(res.data["total_amount"]), Decimal("170"))
        self.assertEqual(Decimal(res.data["subtotal_amount"]), Decimal("200"))
        self.assertEqual(res.data["promo_code_text"], "HERITAGE20")

    def test_rules(self):
        PromoCode.objects.create(code="MIN", discount_type="flat", value=10, min_order_amount=500)
        PromoCode.objects.create(code="GROUPS", value=10, applies_to="group")
        PromoCode.objects.create(code="FORTS", value=10, scope="place_types", place_types="fort")
        PromoCode.objects.create(code="OLD", value=10, valid_to=timezone.now() - datetime.timedelta(days=1))
        PromoCode.objects.create(code="OFF", value=10, is_active=False)
        for code in ("MIN", "GROUPS", "FORTS", "OLD", "OFF", "NOPE"):
            self.assertEqual(apply(self.visitor, self.booking, code).status_code, 400, code)
        fort = make_museum(place_type=Museum.PlaceType.FORT)
        self.assertEqual(apply(self.visitor, book(self.visitor, fort), "FORTS").status_code, 200)

    def test_limits_and_first_booking(self):
        PromoCode.objects.create(code="ONCE", value=10, per_user_limit=1)
        self.assertEqual(apply(self.visitor, self.booking, "ONCE").status_code, 200)
        other = book(self.visitor, self.museum)
        self.assertEqual(apply(self.visitor, other, "ONCE").status_code, 400)
        PromoCode.objects.create(code="FIRST", value=10, first_booking_only=True)
        book(self.visitor, self.museum, confirm=True)
        self.assertEqual(apply(self.visitor, other, "FIRST").status_code, 400)
        PromoCode.objects.create(code="TOTAL1", value=10, usage_limit=1, per_user_limit=None)
        self.assertEqual(apply(self.visitor, other, "TOTAL1").status_code, 200)
        someone = make_visitor()
        self.assertEqual(apply(someone, book(someone, self.museum), "TOTAL1").status_code, 400)

    def test_remove_restores_and_owner_only(self):
        PromoCode.objects.create(code="FLAT50", discount_type="flat", value=50)
        self.assertEqual(apply(make_visitor(), self.booking, "FLAT50").status_code, 404)
        apply(self.visitor, self.booking, "FLAT50")
        res = client_for(self.visitor).post(f"/api/bookings/{self.booking.reference}/remove-code/")
        self.assertEqual(res.status_code, 200)
        self.assertEqual(Decimal(res.data["total_amount"]), Decimal("200"))
        self.assertIsNone(res.data["promo_code"])

    def test_full_discount_confirms_free(self):
        PromoCode.objects.create(code="FREE", value=100)
        res = apply(self.visitor, self.booking, "FREE")
        self.assertEqual(res.data["status"], Booking.Status.CONFIRMED)
        self.assertEqual(res.data["payment_method"], Booking.PaymentMethod.FREE)

    def test_expired_hold_rejected(self):
        PromoCode.objects.create(code="LATE", value=10)
        age_booking(self.booking, 60)
        self.assertEqual(apply(self.visitor, self.booking, "LATE").status_code, 400)


class GiftVoucherTests(APITestCase):
    def setUp(self):
        super().setUp()
        self.museum = make_museum()
        self.visitor = make_visitor()
        self.admin = make_admin()

    def issue(self, value="150", **extra):
        res = client_for(self.admin).post(
            "/api/admin/gift-vouchers/", {"initial_value": value, "recipient_name": "Meera", **extra}, format="json"
        )
        self.assertEqual(res.status_code, 201, res.data)
        return GiftVoucher.objects.get(pk=res.data["id"])

    def test_partial_voucher_then_release_on_expiry(self):
        voucher = self.issue("150")
        self.assertTrue(voucher.code.startswith("GV-"))
        booking = book(self.visitor, self.museum, qty=4)
        res = apply(self.visitor, booking, voucher.code.lower())
        self.assertEqual(Decimal(res.data["voucher_amount"]), Decimal("150"))
        self.assertEqual(Decimal(res.data["total_amount"]), Decimal("50"))
        self.assertEqual(res.data["voucher_code"], voucher.code)
        voucher.refresh_from_db()
        self.assertEqual(voucher.balance, 0)
        # Hold expires via the bulk update (no signal): the sweep returns the money.
        age_booking(booking, 60)
        res = client_for(self.admin).get(f"/api/admin/gift-vouchers/lookup/?code={voucher.code}")
        self.assertEqual(Decimal(res.data["balance"]), Decimal("150"))

    def test_voucher_covers_all_and_cancel_restores(self):
        voucher = self.issue("500")
        booking = book(self.visitor, self.museum, qty=2)  # 100, far in the future
        res = apply(self.visitor, booking, voucher.code)
        self.assertEqual(res.data["status"], Booking.Status.CONFIRMED)
        voucher.refresh_from_db()
        self.assertEqual(voucher.balance, Decimal("400"))
        booking_services.cancel_booking(Booking.objects.get(pk=booking.pk))
        voucher.refresh_from_db()
        self.assertEqual(voucher.balance, Decimal("500"))

    def test_paid_cancel_refunds_cash_and_restores_voucher(self):
        voucher = self.issue("50")
        booking = book(self.visitor, self.museum, qty=4)
        apply(self.visitor, booking, voucher.code)
        booking.refresh_from_db()
        booking_services.confirm_payment(booking, Booking.PaymentMethod.UPI)
        booking = booking_services.cancel_booking(booking)
        self.assertEqual(booking.refund_amount, Decimal("150"))
        voucher.refresh_from_db()
        self.assertEqual(voucher.balance, Decimal("50"))
        # Releasing again does nothing.
        self.assertEqual(booking_services.Booking.objects.get(pk=booking.pk).voucher_amount, Decimal("50"))
        from .services import release_for_booking
        self.assertEqual(release_for_booking(booking), 0)

    def test_promo_after_voucher_returns_excess(self):
        voucher = self.issue("190")
        PromoCode.objects.create(code="HALF", value=50)
        booking = book(self.visitor, self.museum, qty=4)  # 200
        apply(self.visitor, booking, voucher.code)
        res = apply(self.visitor, booking, "HALF")
        self.assertEqual(res.status_code, 200, res.data)
        self.assertEqual(Decimal(res.data["voucher_amount"]), Decimal("100"))
        self.assertEqual(Decimal(res.data["total_amount"]), Decimal("0"))
        voucher.refresh_from_db()
        self.assertEqual(voucher.balance, Decimal("90"))

    def test_remove_voucher_and_inactive(self):
        voucher = self.issue("100")
        booking = book(self.visitor, self.museum, qty=4)
        apply(self.visitor, booking, voucher.code)
        client_for(self.visitor).post(f"/api/bookings/{booking.reference}/remove-code/", {"kind": "voucher"})
        voucher.refresh_from_db()
        self.assertEqual(voucher.balance, Decimal("100"))
        client_for(self.admin).post(f"/api/admin/gift-vouchers/{voucher.pk}/deactivate/")
        self.assertEqual(apply(self.visitor, booking, voucher.code).status_code, 400)

    def test_permissions_and_email(self):
        staff = make_staff(self.museum)
        self.assertEqual(client_for(staff).get("/api/admin/gift-vouchers/").status_code, 200)
        self.assertEqual(client_for(staff).get("/api/admin/promo-codes/").status_code, 403)
        self.assertEqual(client_for(self.visitor).get("/api/admin/gift-vouchers/").status_code, 403)
        res = client_for(staff).post("/api/admin/gift-vouchers/", {
            "initial_value": "300", "recipient_email": "meera@example.com", "send_email": True,
        }, format="json")
        self.assertEqual(res.status_code, 201, res.data)
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn(res.data["code"], mail.outbox[0].body)
        self.assertEqual(client_for(staff).delete(f"/api/admin/gift-vouchers/{res.data['id']}/").status_code, 403)

    def test_admin_promo_crud_validation(self):
        c = client_for(self.admin)
        res = c.post("/api/admin/promo-codes/", {"code": "diwali", "value": "10"}, format="json")
        self.assertEqual(res.status_code, 201, res.data)
        self.assertEqual(res.data["code"], "DIWALI")
        self.assertEqual(c.post("/api/admin/promo-codes/", {"code": "Diwali", "value": "5"}, format="json").status_code, 400)
        self.assertEqual(c.post("/api/admin/promo-codes/", {"code": "X", "value": "150"}, format="json").status_code, 400)
        self.assertEqual(
            c.post("/api/admin/promo-codes/", {"code": "Y", "value": "5", "scope": "museums"}, format="json").status_code, 400
        )
        listed = c.get("/api/admin/promo-codes/").data
        rows = listed["results"] if isinstance(listed, dict) else listed
        self.assertEqual(rows[0]["uses_count"], 0)
