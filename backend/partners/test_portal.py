"""Partner portal (role partner): permissions, scoping to their own places, and the numbers."""
import datetime
from decimal import Decimal

from django.utils import timezone

from accounts.models import User
from bookings.models import Booking
from bookings.tests.factories import (
    APITestCase, at, client_for, first_slot, make_admin, make_museum, make_staff, make_user, make_visitor,
)
from museums.models import Review

from .models import PartnerAccount, Settlement


def make_partner(*museums):
    user = make_user(User.Role.PARTNER)
    user.partner_places.set(museums)
    return user


class PartnerRoleTests(APITestCase):
    def setUp(self):
        super().setUp()
        self.place, self.other = make_museum("Red Fort"), make_museum("Other Fort")
        self.partner = make_partner(self.place)

    def test_partner_is_not_a_panel_user(self):
        self.assertFalse(self.partner.is_panel_user)
        self.assertTrue(self.partner.is_partner)
        c = client_for(self.partner)
        for url in (
            "/api/admin/dashboard/", "/api/admin/price-rules/", "/api/auth/users/", "/api/settlements/",
            f"/api/admin/pricing-suggestions/?museum={self.place.slug}", "/api/admin/closures/",
        ):
            self.assertEqual(c.get(url).status_code, 403, url)

    def test_partner_place_link_grants_no_staff_rights(self):
        # Partners are linked through User.partner_places, never Museum.staff (which lets people sell and scan).
        self.assertFalse(self.place.staff.filter(pk=self.partner.pk).exists())
        r = client_for(self.partner).get("/api/museums/", {"assigned": 1})
        self.assertEqual(r.status_code, 200)

    def test_only_partners_reach_the_portal(self):
        for user in (make_visitor(), make_staff(self.place), make_admin(), make_user(User.Role.AGENT)):
            self.assertEqual(client_for(user).get("/api/partner/overview/").status_code, 403, user.role)
        self.assertEqual(client_for().get("/api/partner/overview/").status_code, 401)
        self.partner.is_active = False
        self.partner.save()
        self.assertIn(client_for(self.partner).get("/api/partner/me/").status_code, (401, 403))

    def test_only_their_places(self):
        c = client_for(self.partner)
        me = c.get("/api/partner/me/").data
        self.assertEqual([p["slug"] for p in me["places"]], [self.place.slug])
        for url in ("overview", "trend", "reviews", "settlements"):
            self.assertEqual(c.get(f"/api/partner/{url}/", {"museum": self.other.slug}).status_code, 403, url)
            self.assertEqual(c.get(f"/api/partner/{url}/", {"museum": self.place.slug}).status_code, 200, url)
        places = c.get("/api/partner/overview/").data["places"]
        self.assertEqual([p["slug"] for p in places], [self.place.slug])


class PartnerNumbersTests(APITestCase):
    def setUp(self):
        super().setUp()
        self.place, self.second, self.other = make_museum("Red Fort"), make_museum("National Museum"), make_museum()
        self.partner = make_partner(self.place, self.second)
        self.visitor = make_visitor()
        self.today = timezone.localdate()
        self.month_start = self.today.replace(day=1)
        self.last_month_day = self.month_start - datetime.timedelta(days=5)
        self.client_ = client_for(self.partner)

    def booking(self, museum, visit_date, visitors, amount, *, status=Booking.Status.CONFIRMED, paid_on=None,
                voucher="0", refund="0", cancelled_on=None):
        return Booking.objects.create(
            user=self.visitor, museum=museum, slot=first_slot(museum), visit_date=visit_date, status=status,
            total_visitors=visitors, total_amount=Decimal(amount), voucher_amount=Decimal(voucher),
            visitor_name="Asha", paid_at=at(paid_on, 12) if paid_on else None,
            refund_amount=Decimal(refund), cancelled_at=at(cancelled_on, 13) if cancelled_on else None,
        )

    def test_overview_numbers(self):
        t, lm = self.today, self.last_month_day
        self.booking(self.place, t, 4, "200", paid_on=t, voucher="50")             # today: 4 visitors, Rs 250
        self.booking(self.place, t, 2, "100", paid_on=t, status=Booking.Status.CHECKED_IN)
        self.booking(self.place, t, 9, "900", status=Booking.Status.PENDING)       # unpaid: not counted
        self.booking(self.place, lm, 3, "300", paid_on=lm)                         # last month
        self.booking(self.place, lm, 5, "500", paid_on=lm, status=Booking.Status.CANCELLED,
                     refund="450", cancelled_on=t)                                 # refunded today
        self.booking(self.second, t, 7, "700", paid_on=t)
        self.booking(self.other, t, 50, "5000", paid_on=t)                         # not their place
        data = self.client_.get("/api/partner/overview/").data
        red = next(p for p in data["places"] if p["slug"] == self.place.slug)
        self.assertEqual(red["today"], {"visitors": 6, "bookings": 2, "revenue": Decimal("350.00"), "refunds": Decimal("450.00")})
        self.assertEqual(red["last_month"]["visitors"], 3)
        self.assertEqual(red["last_month"]["revenue"], Decimal("300.00"))
        self.assertEqual(red["last_month"]["refunds"], Decimal("0.00"))
        self.assertEqual(red["this_month"]["visitors"], 6)
        self.assertEqual(data["totals"]["today"]["visitors"], 13)  # 6 + 7, never the other place's 50
        self.assertEqual(data["totals"]["today"]["revenue"], Decimal("1050.00"))
        one = self.client_.get("/api/partner/overview/", {"museum": self.second.slug}).data
        self.assertEqual([p["slug"] for p in one["places"]], [self.second.slug])

    def test_trend(self):
        yesterday = self.today - datetime.timedelta(days=1)
        self.booking(self.place, yesterday, 4, "400", paid_on=yesterday)
        self.booking(self.other, yesterday, 40, "4000", paid_on=yesterday)
        r = self.client_.get("/api/partner/trend/", {"days": 90})
        self.assertEqual(r.data["days"], 90)
        self.assertEqual(len(r.data["daily"]), 90)
        self.assertEqual(r.data["daily"][-1]["date"], self.today)
        day = r.data["daily"][-2]
        self.assertEqual((day["visitors"], day["revenue"]), (4, Decimal("400.00")))
        self.assertEqual(len(self.client_.get("/api/partner/trend/", {"days": 7}).data["daily"]), 30)  # only 30 / 90

    def test_reviews_and_settlements(self):
        Review.objects.create(museum=self.place, user=self.visitor, rating=5, comment="Grand")
        Review.objects.create(museum=self.other, user=self.visitor, rating=1, comment="Not theirs")
        Review.objects.create(museum=self.second, user=make_visitor(), rating=3, comment="Hidden", is_published=False)
        r = self.client_.get("/api/partner/reviews/").data
        self.assertEqual([x["comment"] for x in r["results"]], ["Grand"])

        lm = self.last_month_day
        common = {"period_start": lm, "period_end": lm, "net_payable": Decimal("100")}
        Settlement.objects.create(museum=self.place, status=Settlement.Status.PAID, paid_reference="UTR1", **common)
        Settlement.objects.create(museum=self.second, status=Settlement.Status.DRAFT, **common)
        Settlement.objects.create(museum=self.other, status=Settlement.Status.PAID, **common)
        PartnerAccount.objects.create(museum=self.place, bank_name="SBI", account_number="1234567890")
        rows = self.client_.get("/api/partner/settlements/").data["results"]
        self.assertEqual([(x["museum_slug"], x["paid_reference"]) for x in rows], [(self.place.slug, "UTR1")])
        self.assertEqual(rows[0]["payout_account"], {"bank_name": "SBI", "account_number": "XXXX7890"})
        self.assertNotIn("approved_by_email", rows[0])


class AdminPartnerUserTests(APITestCase):
    def setUp(self):
        super().setUp()
        self.admin = make_admin()
        self.place = make_museum()

    def test_admin_creates_partner_and_assigns_places(self):
        c = client_for(self.admin)
        r = c.post("/api/auth/users/partners/", {
            "email": "Owner@Example.com", "password": "Heritage#2026", "first_name": "Ravi", "museums": [self.place.slug],
        }, format="json")
        self.assertEqual(r.status_code, 201, r.data)
        self.assertEqual((r.data["email"], r.data["role"], r.data["is_panel_user"]), ("owner@example.com", "partner", False))
        uid = r.data["id"]
        self.assertEqual([m["slug"] for m in c.get(f"/api/auth/users/{uid}/partner-places/").data["museums"]], [self.place.slug])
        second = make_museum()
        r = c.put(f"/api/auth/users/{uid}/partner-places/", {"museums": [second.slug]}, format="json")
        self.assertEqual([m["slug"] for m in r.data["museums"]], [second.slug])
        self.assertEqual(c.put(f"/api/auth/users/{uid}/partner-places/", {"museums": ["nope"]}, format="json").status_code, 400)
        # Bad input and non-admins.
        self.assertEqual(c.post("/api/auth/users/partners/", {"email": "x@example.com", "password": "Heritage#2026",
                                                              "museums": []}, format="json").status_code, 400)
        staff = make_staff(self.place)
        self.assertEqual(client_for(staff).post("/api/auth/users/partners/", {}, format="json").status_code, 403)
        self.assertEqual(c.put(f"/api/auth/users/{staff.id}/partner-places/", {"museums": []}, format="json").status_code, 400)

    def test_role_can_be_switched_to_partner(self):
        user = make_visitor()
        r = client_for(self.admin).patch(f"/api/auth/users/{user.id}/", {"role": "partner"}, format="json")
        self.assertEqual(r.status_code, 200, r.data)
        self.assertEqual(r.data["role"], "partner")
