"""Tour operator portal, partner settlements and self-service kiosks."""
import datetime
from decimal import Decimal

from django.utils import timezone

from accounts.models import User
from bookings import services as booking_services
from bookings.models import Booking
from bookings.tests.factories import (
    ALL_DAY, APITestCase, add_slot, book, booking_payload, client_for, first_slot, future_open_date, make_admin,
    make_museum, make_staff, make_user, make_visitor, ticket,
)

from .models import AgentProfile, KioskDevice, PartnerAccount, Settlement
from .services import generate_settlements


def make_agent(credit="1000", commission="10"):
    user = make_visitor()
    profile = AgentProfile.objects.create(
        user=user, company_name="Yatra Tours", contact_phone="9876543210", credit_limit=Decimal(credit),
        commission_percent=Decimal(commission), status=AgentProfile.Status.APPROVED, is_approved=True,
    )
    user.role = User.Role.AGENT
    user.save()
    return profile


class RoleTests(APITestCase):
    def test_new_roles_are_not_panel_users(self):
        for role in (User.Role.AGENT, User.Role.KIOSK):
            user = make_user(role)
            self.assertFalse(user.is_panel_user)
            self.assertFalse(user.is_admin_role)
            self.assertEqual(client_for(user).get("/api/admin/dashboard/").status_code, 403)


class AgentApplicationTests(APITestCase):
    def setUp(self):
        super().setUp()
        self.visitor = make_visitor()
        self.admin = make_admin()

    def test_apply_and_approve(self):
        c = client_for(self.visitor)
        self.assertIsNone(c.get("/api/agents/me/").data["profile"])
        res = c.post("/api/agents/apply/", {"company_name": "Ganga Travels", "contact_phone": "9876543210",
                                            "gstin": "29abcde1234f1z5"}, format="json")
        self.assertEqual(res.status_code, 201, res.data)
        self.assertEqual(res.data["status"], "pending")
        self.assertEqual(res.data["gstin"], "29ABCDE1234F1Z5")
        # Not approved yet: cannot book on account.
        self.assertEqual(c.get("/api/agents/bookings/").status_code, 403)
        self.assertEqual(client_for(self.visitor).post("/api/agents/apply/", {"company_name": "X", "contact_phone": "1"},
                                                       format="json").status_code, 400)

        pid = res.data["id"]
        admin = client_for(self.admin)
        self.assertEqual(client_for(self.visitor).post(f"/api/admin/agents/{pid}/approve/").status_code, 403)
        res = admin.post(f"/api/admin/agents/{pid}/approve/", {"credit_limit": "5000", "commission_percent": "7.5"},
                         format="json")
        self.assertEqual(res.status_code, 200, res.data)
        self.assertEqual(res.data["status"], "approved")
        self.assertEqual(Decimal(res.data["credit_limit"]), Decimal("5000"))
        self.visitor.refresh_from_db()
        self.assertEqual(self.visitor.role, User.Role.AGENT)
        self.assertFalse(self.visitor.is_panel_user)
        me = client_for(self.visitor).get("/api/agents/me/").data
        self.assertEqual(Decimal(me["dashboard"]["credit_available"]), Decimal("5000"))
        # Already a partner: cannot apply again.
        self.assertEqual(client_for(self.visitor).post("/api/agents/apply/", {
            "company_name": "Again", "contact_phone": "9876543210"}, format="json").status_code, 400)

        # Suspend: role goes back to visitor, booking is blocked.
        res = admin.post(f"/api/admin/agents/{pid}/reject/", {"reason": "Unpaid dues"}, format="json")
        self.assertEqual(res.data["status"], "suspended")
        self.visitor.refresh_from_db()
        self.assertEqual(self.visitor.role, User.Role.VISITOR)
        self.assertEqual(client_for(self.visitor).get("/api/agents/bookings/").status_code, 403)

    def test_reject_then_reapply_and_staff_cannot_apply(self):
        res = client_for(self.visitor).post("/api/agents/apply/", {"company_name": "A", "contact_phone": "9876543210"},
                                            format="json")
        admin = client_for(self.admin)
        self.assertEqual(admin.post(f"/api/admin/agents/{res.data['id']}/reject/").data["status"], "rejected")
        again = client_for(self.visitor).post("/api/agents/apply/", {"company_name": "B", "contact_phone": "9876543210"},
                                              format="json")
        self.assertEqual(again.status_code, 201)
        self.assertEqual(again.data["status"], "pending")
        self.assertEqual(AgentProfile.objects.count(), 1)
        self.assertEqual(admin.get("/api/admin/agents/?status=pending").data["count"], 1)
        staff = make_staff()
        self.assertEqual(client_for(staff).post("/api/agents/apply/", {"company_name": "S", "contact_phone": "9876543210"},
                                                format="json").status_code, 400)


class AgentBookingTests(APITestCase):
    def setUp(self):
        super().setUp()
        self.museum = make_museum()
        self.slot = first_slot(self.museum)
        self.day = future_open_date(self.museum)
        self.profile = make_agent(credit="1000", commission="10")
        self.client_ = client_for(self.profile.user)

    def payload(self, qty=4, **extra):
        p = booking_payload(self.museum, self.slot, self.day, qty=qty, **extra)
        p.pop("visitor_email")
        p.pop("visitor_phone")
        return p

    def test_on_account_booking_and_credit_limit(self):
        res = self.client_.post("/api/agents/bookings/", self.payload(qty=10), format="json")  # 10 x 50 = 500
        self.assertEqual(res.status_code, 201, res.data)
        self.assertEqual(res.data["status"], "confirmed")
        self.assertEqual(res.data["channel"], "agent")
        self.assertEqual(res.data["payment_method"], "on_account")
        self.assertEqual(Decimal(res.data["commission_amount"]), Decimal("50"))
        self.assertEqual(res.data["visitor_email"], self.profile.user.email)
        self.profile.refresh_from_db()
        self.assertEqual(self.profile.balance, Decimal("450"))
        # 20 x 50 = 1000 -> net 900; 450 + 900 > 1000: refused and nothing is kept.
        res = self.client_.post("/api/agents/bookings/", self.payload(qty=20), format="json")
        self.assertEqual(res.status_code, 400)
        self.assertIn("credit", res.data)
        self.assertEqual(Booking.objects.filter(agent=self.profile.user).count(), 1)
        self.assertEqual(Booking.objects.count(), 1)
        # Individuals are limited to 20 tickets.
        self.assertEqual(self.client_.post("/api/agents/bookings/", self.payload(qty=21), format="json").status_code, 400)
        listed = self.client_.get("/api/agents/bookings/").data
        self.assertEqual(listed["count"], 1)
        self.assertTrue(listed["results"][0]["agent_can_cancel"])
        # The agent can open the ticket like any booking owner.
        self.assertEqual(self.client_.get(f"/api/bookings/{listed['results'][0]['reference']}/").status_code, 200)

    def test_group_booking_uses_group_rules(self):
        self.profile.credit_limit = Decimal("100000")
        self.profile.save()
        payload = self.payload(qty=30, group_type="tour_operator", organisation_name="Yatra Tours")
        res = self.client_.post("/api/agents/bookings/", payload, format="json")
        self.assertEqual(res.status_code, 201, res.data)
        self.assertTrue(res.data["is_group"])
        self.assertEqual(Decimal(res.data["total_amount"]), Decimal("1350"))  # 1500 - 10% group discount
        self.assertEqual(Decimal(res.data["commission_amount"]), Decimal("135"))
        small = self.payload(qty=5, group_type="tour_operator", organisation_name="Yatra Tours")
        self.assertEqual(self.client_.post("/api/agents/bookings/", small, format="json").status_code, 400)

    def test_cancel_before_cutoff_and_payments(self):
        ref = self.client_.post("/api/agents/bookings/", self.payload(qty=10), format="json").data["reference"]
        res = self.client_.post(f"/api/agents/bookings/{ref}/cancel/")
        self.assertEqual(res.status_code, 200, res.data)
        self.assertEqual(res.data["status"], "cancelled")
        self.assertEqual(res.data["refund_status"], "")  # nothing through a gateway
        self.profile.refresh_from_db()
        self.assertEqual(self.profile.balance, Decimal("0"))

        # Inside 24 hours of the slot: not allowed.
        today_slot = add_slot(self.museum, start=datetime.time(23, 0), end=datetime.time(23, 59))
        booking = booking_services.create_booking(
            user=self.profile.user, museum=self.museum, slot=today_slot, visit_date=timezone.localdate(),
            items=[{"ticket_type": ticket(self.museum), "quantity": 2}], visitor_name="X",
            channel=Booking.Channel.AGENT,
        )
        Booking.objects.filter(pk=booking.pk).update(agent=self.profile.user)
        self.assertEqual(self.client_.post(f"/api/agents/bookings/{booking.reference}/cancel/").status_code, 400)

        # Admin records a payment that reduces the balance.
        self.client_.post("/api/agents/bookings/", self.payload(qty=10), format="json")
        admin = client_for(make_admin())
        res = admin.post(f"/api/admin/agents/{self.profile.pk}/payments/", {"amount": "200", "reference": "UTR123"},
                         format="json")
        self.assertEqual(res.status_code, 201, res.data)
        self.assertEqual(Decimal(res.data["agent"]["balance"]), Decimal("250"))
        self.assertEqual(len(admin.get(f"/api/admin/agents/{self.profile.pk}/payments/").data), 1)
        self.assertEqual(self.client_.post(f"/api/admin/agents/{self.profile.pk}/payments/",
                                           {"amount": "1", "reference": "x"}, format="json").status_code, 403)

    def test_generic_cancel_keeps_balance_in_step(self):
        ref = self.client_.post("/api/agents/bookings/", self.payload(qty=10), format="json").data["reference"]
        self.client_.post(f"/api/bookings/{ref}/cancel/")
        self.profile.refresh_from_db()
        self.assertEqual(self.profile.balance, Decimal("0"))

    def test_statement(self):
        self.client_.post("/api/agents/bookings/", self.payload(qty=10), format="json")
        ref = self.client_.post("/api/agents/bookings/", self.payload(qty=2), format="json").data["reference"]
        self.client_.post(f"/api/agents/bookings/{ref}/cancel/")
        month = f"{timezone.localdate():%Y-%m}"
        res = self.client_.get(f"/api/agents/statement/?month={month}")
        self.assertEqual(res.status_code, 200, res.data)
        self.assertEqual(res.data["booking_count"], 1)
        self.assertEqual(res.data["cancelled_count"], 1)
        self.assertEqual(Decimal(res.data["gross"]), Decimal("500"))
        self.assertEqual(Decimal(res.data["commission"]), Decimal("50"))
        self.assertEqual(Decimal(res.data["net_payable"]), Decimal("450"))
        self.assertEqual(len(res.data["bookings"]), 2)
        self.assertEqual(self.client_.get("/api/agents/statement/?month=2026-13").status_code, 400)
        admin = client_for(make_admin())
        self.assertEqual(admin.get(f"/api/admin/agents/{self.profile.pk}/statement/?month={month}").status_code, 200)

    def test_visitors_cannot_use_agent_endpoints(self):
        visitor = client_for(make_visitor())
        self.assertEqual(visitor.post("/api/agents/bookings/", self.payload(), format="json").status_code, 403)
        self.assertEqual(visitor.get("/api/agents/statement/").status_code, 403)
        self.assertEqual(visitor.get("/api/admin/agents/").status_code, 403)


class SettlementTests(APITestCase):
    def setUp(self):
        super().setUp()
        self.museum = make_museum()
        self.other = make_museum()
        self.admin = make_admin()
        self.visitor = make_visitor()
        self.start = timezone.localdate() - datetime.timedelta(days=10)
        self.end = timezone.localdate() - datetime.timedelta(days=1)

    def paid(self, museum, qty, channel=Booking.Channel.ONLINE, days_ago=5, **kw):
        b = book(self.visitor, museum, qty=qty, confirm=True)
        Booking.objects.filter(pk=b.pk).update(
            channel=channel, paid_at=timezone.now() - datetime.timedelta(days=days_ago), **kw
        )
        return b

    def test_generate_approve_pay(self):
        self.paid(self.museum, 10)                                   # 500 online
        self.paid(self.museum, 4, Booking.Channel.COUNTER)           # 200 counter
        self.paid(self.museum, 2, Booking.Channel.AGENT)             # 100 agent
        self.paid(self.museum, 2, Booking.Channel.KIOSK)             # 100 kiosk
        cancelled = self.paid(self.museum, 6)
        booking_services.cancel_booking(cancelled)                    # refunded: excluded
        self.paid(self.museum, 3, days_ago=40)                       # outside the period
        self.paid(self.other, 1)
        PartnerAccount.objects.create(museum=self.other, platform_fee_percent=Decimal("10"))

        c = client_for(self.admin)
        res = c.post("/api/admin/settlements/generate/", {"from": str(self.start), "to": str(self.end)}, format="json")
        self.assertEqual(res.status_code, 201, res.data)
        self.assertEqual(len(res.data["created"]), 2)
        s = Settlement.objects.get(museum=self.museum)
        self.assertEqual(s.gross_online, Decimal("500"))
        self.assertEqual(s.gross_counter, Decimal("200"))
        self.assertEqual(s.gross_agent, Decimal("100"))
        self.assertEqual(s.gross_kiosk, Decimal("100"))
        self.assertEqual(s.booking_count, 4)
        self.assertEqual(s.platform_fee, Decimal("45.00"))  # 5% of 900
        self.assertEqual(s.gst_on_fee, Decimal("8.10"))
        self.assertEqual(s.net_payable, Decimal("646.90"))  # 700 collected by the platform - fee - GST
        self.assertEqual(Settlement.objects.get(museum=self.other).platform_fee_percent, Decimal("10"))

        # Regenerating refreshes the draft instead of duplicating it.
        res = c.post("/api/admin/settlements/generate/", {"from": str(self.start), "to": str(self.end)}, format="json")
        self.assertEqual(len(res.data["updated"]), 2)
        self.assertEqual(Settlement.objects.count(), 2)

        self.assertEqual(c.post(f"/api/admin/settlements/{s.pk}/mark-paid/", {"reference": "X"}).status_code, 400)
        self.assertEqual(c.post(f"/api/admin/settlements/{s.pk}/approve/").data["status"], "approved")
        self.assertEqual(c.post(f"/api/admin/settlements/{s.pk}/mark-paid/").status_code, 400)
        res = c.post(f"/api/admin/settlements/{s.pk}/mark-paid/", {"reference": "UTR99"}, format="json")
        self.assertEqual(res.data["status"], "paid")
        self.assertEqual(c.delete(f"/api/admin/settlements/{s.pk}/").status_code, 400)
        # Approved/paid settlements are not regenerated, and overlapping periods are skipped.
        res = c.post("/api/admin/settlements/generate/", {"from": str(self.start - datetime.timedelta(days=3)),
                                                          "to": str(self.end)}, format="json")
        self.assertEqual(len(res.data["skipped"]), 2)
        # Today is not settled yet.
        res = c.post("/api/admin/settlements/generate/", {"from": str(self.end), "to": str(timezone.localdate())},
                     format="json")
        self.assertEqual(res.status_code, 400)

        csv = c.get("/api/settlements/export.csv")
        self.assertEqual(csv.status_code, 200)
        self.assertIn("Net payable", csv.content.decode("utf-8-sig"))
        detail = c.get(f"/api/settlements/{s.pk}/").data
        self.assertEqual(len(detail["bookings"]), 4)

    def test_late_refund_is_deducted(self):
        b = self.paid(self.museum, 10, days_ago=30)
        booking_services.cancel_booking(b)  # visit is in the future: full refund
        Booking.objects.filter(pk=b.pk).update(cancelled_at=timezone.now() - datetime.timedelta(days=3))
        self.paid(self.museum, 20)
        created, _, _ = generate_settlements(
            start=self.start, end=self.end, by=self.admin)
        s = created[0]
        self.assertEqual(s.refunds, Decimal("500"))
        self.assertEqual(s.net_payable, Decimal("1000") - Decimal("500") - Decimal("50") - Decimal("9"))

    def test_staff_see_only_their_places_read_only(self):
        self.paid(self.museum, 2)
        self.paid(self.other, 2)
        client_for(self.admin).post("/api/admin/settlements/generate/",
                                    {"from": str(self.start), "to": str(self.end)}, format="json")
        staff = client_for(make_staff(self.museum))
        res = staff.get("/api/settlements/")
        self.assertEqual(res.data["count"], 1)
        self.assertEqual(res.data["results"][0]["museum_slug"], self.museum.slug)
        sid = Settlement.objects.get(museum=self.museum).pk
        self.assertEqual(staff.post(f"/api/admin/settlements/{sid}/approve/").status_code, 403)
        self.assertEqual(staff.get(f"/api/settlements/{Settlement.objects.get(museum=self.other).pk}/").status_code, 404)
        self.assertEqual(client_for(self.visitor).get("/api/settlements/").status_code, 403)

    def test_partner_account_masks_bank_number(self):
        c = client_for(self.admin)
        res = c.post("/api/admin/partner-accounts/", {
            "museum": self.museum.slug, "account_number": "123456789012", "ifsc": "sbin0001234",
            "razorpay_account_id": "acc_ABC123", "platform_fee_percent": "4",
        }, format="json")
        self.assertEqual(res.status_code, 201, res.data)
        self.assertNotIn("account_number", res.data)
        self.assertEqual(res.data["masked_account_number"], "XXXX9012")
        self.assertEqual(res.data["ifsc"], "SBIN0001234")
        bad = c.post("/api/admin/partner-accounts/", {"museum": self.other.slug, "razorpay_account_id": "x"}, format="json")
        self.assertEqual(bad.status_code, 400)


class KioskTests(APITestCase):
    def setUp(self):
        super().setUp()
        self.museum = make_museum(slots=(ALL_DAY + (100,),))
        self.other = make_museum()
        self.admin = make_admin()

    def create_kiosk(self):
        res = client_for(self.admin).post("/api/admin/kiosks/", {
            "name": "Gate 2 kiosk", "email": "Kiosk1@Example.com", "password": "Strong-pass-1234",
            "museums": [self.museum.slug],
        }, format="json")
        self.assertEqual(res.status_code, 201, res.data)
        return KioskDevice.objects.get(pk=res.data["id"])

    def test_admin_creates_kiosk_account(self):
        device = self.create_kiosk()
        self.assertEqual(device.user.role, User.Role.KIOSK)
        self.assertEqual(device.user.email, "kiosk1@example.com")
        self.assertFalse(device.user.is_panel_user)
        res = client_for(self.admin).patch(f"/api/admin/kiosks/{device.pk}/", {"is_active": False}, format="json")
        self.assertEqual(res.status_code, 200, res.data)
        device.user.refresh_from_db()
        self.assertFalse(device.user.is_active)
        self.assertEqual(client_for(make_visitor()).get("/api/admin/kiosks/").status_code, 403)

    def test_kiosk_sale_flow(self):
        device = self.create_kiosk()
        kiosk = client_for(device.user)
        me = kiosk.get("/api/kiosk/me/").data
        self.assertEqual([m["slug"] for m in me["museums"]], [self.museum.slug])
        session = kiosk.get(f"/api/kiosk/session/?museum={self.museum.slug}")
        self.assertEqual(session.status_code, 200, session.data)
        slot = session.data["slots"][0]
        self.assertTrue(slot["running"] and slot["bookable"])
        res = kiosk.post("/api/kiosk/bookings/", {
            "museum": self.museum.slug, "slot": slot["id"],
            "items": [{"ticket_type": ticket(self.museum).id, "quantity": 2}],
        }, format="json")
        self.assertEqual(res.status_code, 201, res.data)
        self.assertEqual(res.data["status"], "pending")
        self.assertEqual(res.data["channel"], "kiosk")
        self.assertEqual(res.data["visitor_name"], "Kiosk visitor")
        ref = res.data["reference"]
        paid = kiosk.post(f"/api/bookings/{ref}/pay/", {"method": "upi"}, format="json")
        self.assertEqual(paid.status_code, 200, paid.data)
        self.assertEqual(paid.data["status"], "confirmed")

        # Not its place, not today, not a kiosk.
        self.assertEqual(kiosk.get(f"/api/kiosk/session/?museum={self.other.slug}").status_code, 403)
        self.assertEqual(kiosk.post("/api/kiosk/bookings/", {
            "museum": self.other.slug, "slot": first_slot(self.other).id,
            "items": [{"ticket_type": ticket(self.other).id, "quantity": 1}],
        }, format="json").status_code, 403)
        self.assertEqual(kiosk.post("/api/kiosk/bookings/", {
            "museum": self.museum.slug, "slot": slot["id"], "visit_date": str(timezone.localdate() + datetime.timedelta(days=1)),
            "items": [{"ticket_type": ticket(self.museum).id, "quantity": 1}],
        }, format="json").status_code, 400)
        self.assertEqual(client_for(make_visitor()).get("/api/kiosk/me/").status_code, 403)
        device.is_active = False
        device.save()
        self.assertEqual(kiosk.get("/api/kiosk/me/").status_code, 403)
