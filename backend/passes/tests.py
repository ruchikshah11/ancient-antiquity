"""Combo passes (purchase, payment, cancellation, gate admission) and multiple gates / live occupancy."""
import datetime
from decimal import Decimal
from io import StringIO
from unittest import mock

from django.core.management import call_command
from django.test import override_settings
from django.utils import timezone

from bookings.models import Booking, GateScan
from bookings.tests.factories import (
    ALL_DAY, APITestCase, at, book, client_for, frozen_now, make_admin, make_museum, make_staff, make_visitor,
)
from bookings.tests.test_payments import KEY_SECRET, FakeRazorpay, sign
from museums.models import Gate
from passes import services
from passes.models import ComboPass, ComboPassSite, PassOrder, PassVisit


def make_pass(*museums, validity_days=1, prices=("100", "1000", "50", "0"), **extra):
    combo = ComboPass.objects.create(
        name=extra.pop("name", "Test Pass"), validity_days=validity_days,
        price_indian=Decimal(prices[0]), price_foreign=Decimal(prices[1]),
        price_student=Decimal(prices[2]), price_child=Decimal(prices[3]), **extra,
    )
    for i, m in enumerate(museums):
        ComboPassSite.objects.create(combo_pass=combo, museum=m, sort_order=i)
    return combo


def buy(user, combo, start_date=None, confirm=True, **counts):
    order = services.create_order(
        user=user, combo_pass=combo, start_date=start_date or timezone.localdate(),
        counts=counts or {"indian": 2}, visitor_name="Asha Rao", visitor_email=user.email,
    )
    if confirm and order.status == PassOrder.Status.PENDING:
        services.confirm_payment(order, "upi")
    order.refresh_from_db()
    return order


class PassBase(APITestCase):
    def setUp(self):
        super().setUp()
        self.today = timezone.localdate()
        self.m1 = make_museum(slots=[(*ALL_DAY, 200)])
        self.m2 = make_museum(slots=[(*ALL_DAY, 200)])
        self.m3 = make_museum(slots=[(*ALL_DAY, 200)])
        self.combo = make_pass(self.m1, self.m2, name="Two Sites")
        self.visitor = make_visitor()
        self.client = client_for(self.visitor)


class PublicPassTests(PassBase):
    def test_list_and_detail(self):
        make_pass(self.m1, self.m3, name="Hidden", is_active=False)
        r = client_for().get("/api/passes/")
        self.assertEqual(r.status_code, 200)
        self.assertEqual([p["slug"] for p in r.data], [self.combo.slug])
        self.assertEqual(r.data[0]["from_price"], "50.00")
        self.assertEqual([s["slug"] for s in r.data[0]["sites"]], [self.m1.slug, self.m2.slug])
        r = client_for().get(f"/api/passes/{self.combo.slug}/")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.data["prices"]["foreign"], "1000.00")

    def test_inactive_pass_detail_404(self):
        hidden = make_pass(self.m1, self.m3, name="Hidden", is_active=False)
        self.assertEqual(client_for().get(f"/api/passes/{hidden.slug}/").status_code, 404)

    def test_seed_command_is_idempotent(self):
        from museums.models import City, State

        state = State.objects.create(name="Seedland", code="SD")
        city = City.objects.create(name="Seed", state=state)
        slugs = ["taj-mahal-agra", "agra-fort-agra", "fatehpur-sikri-fatehpur-sikri", "red-fort-new-delhi",
                 "qutub-minar-new-delhi", "humayuns-tomb-new-delhi", "group-of-monuments-at-hampi-hampi",
                 "archaeological-museum-hampi-hampi"]
        for slug in slugs:
            make_museum(name=slug, city=city, slug=slug)
        call_command("seed_passes", stdout=StringIO())
        call_command("seed_passes", stdout=StringIO())
        self.assertEqual(ComboPass.objects.filter(slug__endswith="-pass").count(), 3)
        hampi = ComboPass.objects.get(slug="hampi-explorer-pass")
        self.assertEqual(hampi.validity_days, 2)
        self.assertEqual(hampi.sites.count(), 2)
        self.assertIn("Sample pass", hampi.description)


class PurchaseTests(PassBase):
    def payload(self, **extra):
        return {"combo_pass": self.combo.slug, "start_date": str(self.today + datetime.timedelta(days=5)),
                "indian": 2, "foreign": 1, "visitor_name": "Asha Rao", **extra}

    def test_create_pay_and_list(self):
        r = self.client.post("/api/pass-orders/", self.payload(), format="json")
        self.assertEqual(r.status_code, 201, r.data)
        ref = r.data["reference"]
        self.assertTrue(ref.startswith("AP-"))
        self.assertEqual(r.data["status"], "pending")
        self.assertEqual(r.data["total_amount"], "1200.00")
        self.assertEqual(r.data["total_visitors"], 3)
        self.assertEqual(self.client.post(f"/api/pass-orders/{ref}/payment-order/").data, {"provider": "mock"})
        r = self.client.post(f"/api/pass-orders/{ref}/pay/", {"method": "upi"}, format="json")
        self.assertEqual(r.status_code, 200, r.data)
        self.assertEqual(r.data["status"], "confirmed")
        self.assertTrue(r.data["payment_id"].startswith("MOCK-"))
        mine = self.client.get("/api/pass-orders/")
        self.assertEqual([o["reference"] for o in mine.data], [ref])
        self.assertEqual([s["used"] for s in mine.data[0]["sites"]], [False, False])
        # Someone else can't see it
        self.assertEqual(client_for(make_visitor()).get(f"/api/pass-orders/{ref}/").status_code, 404)

    def test_login_required(self):
        self.assertEqual(client_for().post("/api/pass-orders/", self.payload(), format="json").status_code, 401)

    def test_validation(self):
        r = self.client.post("/api/pass-orders/", self.payload(indian=0, foreign=0), format="json")
        self.assertEqual(r.status_code, 400)
        r = self.client.post("/api/pass-orders/", self.payload(start_date=str(self.today - datetime.timedelta(days=1))), format="json")
        self.assertEqual(r.status_code, 400)
        r = self.client.post("/api/pass-orders/", self.payload(indian=21), format="json")
        self.assertEqual(r.status_code, 400)
        self.combo.is_active = False
        self.combo.save()
        self.assertEqual(self.client.post("/api/pass-orders/", self.payload(), format="json").status_code, 400)

    def test_site_closed_on_every_valid_day(self):
        day = self.today + datetime.timedelta(days=5)
        self.m2.closed_weekday = day.weekday()
        self.m2.save()
        r = self.client.post("/api/pass-orders/", self.payload(start_date=str(day)), format="json")
        self.assertEqual(r.status_code, 400)
        self.assertIn(self.m2.name, str(r.data))

    def test_free_party_confirmed_at_once(self):
        r = self.client.post("/api/pass-orders/", self.payload(indian=0, foreign=0, child=2), format="json")
        self.assertEqual(r.status_code, 201, r.data)
        self.assertEqual(r.data["status"], "confirmed")
        self.assertEqual(r.data["payment_method"], "free")

    def test_expired_hold_cannot_be_paid(self):
        order = buy(self.visitor, self.combo, confirm=False)
        PassOrder.objects.filter(pk=order.pk).update(created_at=timezone.now() - datetime.timedelta(minutes=60))
        r = self.client.post(f"/api/pass-orders/{order.reference}/pay/", {"method": "upi"}, format="json")
        self.assertEqual(r.status_code, 400)


class CancelTests(PassBase):
    def test_full_refund_when_unused_and_early(self):
        order = buy(self.visitor, self.combo, start_date=self.today + datetime.timedelta(days=3))
        r = self.client.post(f"/api/pass-orders/{order.reference}/cancel/")
        self.assertEqual(r.status_code, 200, r.data)
        self.assertEqual(r.data["status"], "cancelled")
        self.assertEqual(r.data["refund_amount"], "200.00")
        self.assertEqual(r.data["refund_status"], "processed")

    def test_no_refund_inside_24_hours(self):
        order = buy(self.visitor, self.combo, start_date=self.today)
        r = self.client.post(f"/api/pass-orders/{order.reference}/cancel/")
        self.assertEqual(r.status_code, 200, r.data)
        self.assertEqual(r.data["refund_amount"], "0.00")

    def test_used_pass_cannot_be_cancelled(self):
        order = buy(self.visitor, self.combo)
        PassVisit.objects.create(order=order, museum=self.m1, visited_at=timezone.now(), admitted=2)
        r = self.client.post(f"/api/pass-orders/{order.reference}/cancel/")
        self.assertEqual(r.status_code, 400)


@override_settings(RAZORPAY_KEY_ID="rzp_test_x", RAZORPAY_KEY_SECRET=KEY_SECRET)
class RazorpayPassTests(PassBase):
    def setUp(self):
        super().setUp()
        self.fake = FakeRazorpay()
        patcher = mock.patch("bookings.payments._client", return_value=self.fake)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_checkout_and_verified_payment(self):
        order = buy(self.visitor, self.combo, start_date=self.today + datetime.timedelta(days=3), confirm=False)
        r = self.client.post(f"/api/pass-orders/{order.reference}/payment-order/")
        self.assertEqual(r.status_code, 200, r.data)
        self.assertEqual(r.data["order_id"], "order_TEST1")
        self.assertEqual(r.data["amount"], 20000)
        bad = self.client.post(f"/api/pass-orders/{order.reference}/pay/", {
            "razorpay_order_id": "order_TEST1", "razorpay_payment_id": "pay_1", "razorpay_signature": "nope"})
        self.assertEqual(bad.status_code, 400)
        r = self.client.post(f"/api/pass-orders/{order.reference}/pay/", {
            "razorpay_order_id": "order_TEST1", "razorpay_payment_id": "pay_1",
            "razorpay_signature": sign("order_TEST1|pay_1", KEY_SECRET)})
        self.assertEqual(r.status_code, 200, r.data)
        self.assertEqual(r.data["status"], "confirmed")
        self.assertEqual(r.data["payment_method"], "card")
        # Cancel early: refunded through Razorpay
        r = self.client.post(f"/api/pass-orders/{order.reference}/cancel/")
        self.assertEqual(r.data["refund_status"], "processed")
        self.fake.payment.refund.assert_called_once()


class PassCheckinTests(PassBase):
    def setUp(self):
        super().setUp()
        self.staff = make_staff(self.m1, self.m2, self.m3)
        self.gate_client = client_for(self.staff)

    def checkin(self, reference, museum, **data):
        return self.gate_client.post("/api/bookings/checkin/", {"reference": reference, "museum": museum.slug, **data}, format="json")

    def test_admits_party_once_per_site(self):
        order = buy(self.visitor, self.combo, indian=2, foreign=1)
        r = self.checkin(order.reference.lower(), self.m1)
        self.assertEqual(r.status_code, 200, r.data)
        self.assertEqual(r.data["kind"], "pass")
        self.assertEqual(r.data["total_visitors"], 3)
        self.assertEqual((r.data["sites_used"], r.data["sites_total"]), (1, 2))
        again = self.checkin(order.reference, self.m1)
        self.assertEqual(again.status_code, 400)
        self.assertIn("already used here", str(again.data["reference"]))
        self.assertEqual(self.checkin(order.reference, self.m2).status_code, 200)
        r = self.client.get(f"/api/pass-orders/{order.reference}/")
        self.assertEqual([s["used"] for s in r.data["sites"]], [True, True])

    def test_rejections(self):
        order = buy(self.visitor, self.combo)
        r = self.checkin(order.reference, self.m3)
        self.assertIn("not included", str(r.data["reference"]))
        future = buy(self.visitor, self.combo, start_date=self.today + datetime.timedelta(days=2))
        self.assertIn("valid from", str(self.checkin(future.reference, self.m1).data["reference"]))
        unpaid = buy(self.visitor, self.combo, confirm=False)
        self.assertIn("not been paid", str(self.checkin(unpaid.reference, self.m1).data["reference"]))
        services.cancel_order(order)
        self.assertIn("cancelled", str(self.checkin(order.reference, self.m1).data["reference"]))
        self.assertEqual(self.checkin("AP-ZZZZZZZZ", self.m1).status_code, 400)

    def test_window_expired(self):
        combo2 = make_pass(self.m1, self.m2, validity_days=2, name="Two days")
        order = buy(self.visitor, combo2, start_date=self.today + datetime.timedelta(days=1))
        with frozen_now(at(self.today + datetime.timedelta(days=2), 12)):
            self.assertEqual(self.checkin(order.reference, self.m1).status_code, 200)  # second day: fine
        with frozen_now(at(self.today + datetime.timedelta(days=3), 12)):
            r = self.checkin(order.reference, self.m2)
            self.assertIn("valid until", str(r.data["reference"]))

    def test_staff_must_be_assigned(self):
        order = buy(self.visitor, self.combo)
        outsider = client_for(make_staff(self.m3))
        r = outsider.post("/api/bookings/checkin/", {"reference": order.reference, "museum": self.m1.slug}, format="json")
        self.assertEqual(r.status_code, 403)

    def test_manifest_and_offline_sync(self):
        order = buy(self.visitor, self.combo, indian=3)
        manifest = self.gate_client.get("/api/bookings/gate-manifest/", {"museum": self.m1.slug}).data
        entry = next(t for t in manifest["tickets"] if t["reference"] == order.reference)
        self.assertTrue(entry["is_pass"])
        self.assertEqual(entry["total_visitors"], 3)
        self.assertEqual(entry["status"], "confirmed")
        sync = {"museum": self.m1.slug, "entries": [
            {"reference": order.reference, "checked_in_at": timezone.now().isoformat(), "scan_id": "scan-p1"}]}
        r = self.gate_client.post("/api/bookings/checkin-sync/", sync, format="json")
        self.assertEqual(r.data["results"][0]["result"], "ok", r.data)
        r = self.gate_client.post("/api/bookings/checkin-sync/", sync, format="json")  # resent: harmless
        self.assertEqual(r.data["results"][0]["result"], "ok")
        self.assertEqual(PassVisit.objects.filter(order=order).count(), 1)
        self.assertTrue(PassVisit.objects.get(order=order).offline)
        other = {"museum": self.m1.slug, "entries": [
            {"reference": order.reference, "checked_in_at": timezone.now().isoformat(), "scan_id": "scan-p2"}]}
        r = self.gate_client.post("/api/bookings/checkin-sync/", other, format="json")
        self.assertEqual(r.data["results"][0]["result"], "duplicate")
        manifest = self.gate_client.get("/api/bookings/gate-manifest/", {"museum": self.m1.slug}).data
        entry = next(t for t in manifest["tickets"] if t["reference"] == order.reference)
        self.assertEqual(entry["status"], "checked_in")
        # Not valid at a place outside the pass
        bad = {"museum": self.m3.slug, "entries": [
            {"reference": order.reference, "checked_in_at": timezone.now().isoformat(), "scan_id": "scan-p3"}]}
        self.assertEqual(self.gate_client.post("/api/bookings/checkin-sync/", bad, format="json").data["results"][0]["result"], "invalid")


class GateTests(APITestCase):
    def setUp(self):
        super().setUp()
        self.today = timezone.localdate()
        self.museum = make_museum(slots=[(*ALL_DAY, 200)])
        self.east = Gate.objects.create(museum=self.museum, name="East")
        self.west = Gate.objects.create(museum=self.museum, name="West")
        self.staff = make_staff(self.museum)
        self.client = client_for(self.staff)
        self.visitor = make_visitor()

    def test_online_scan_records_gate(self):
        booking = book(self.visitor, self.museum, visit_date=self.today, qty=2, confirm=True)
        r = self.client.post("/api/bookings/checkin/", {"reference": booking.reference, "gate": self.east.id}, format="json")
        self.assertEqual(r.status_code, 200, r.data)
        self.assertEqual(GateScan.objects.get(booking=booking).gate, self.east)

    def test_gate_of_another_place_rejected(self):
        other = make_museum()
        foreign_gate = Gate.objects.create(museum=other, name="North")
        booking = book(self.visitor, self.museum, visit_date=self.today, confirm=True)
        r = self.client.post("/api/bookings/checkin/", {"reference": booking.reference, "gate": foreign_gate.id}, format="json")
        self.assertEqual(r.status_code, 400)
        self.assertFalse(GateScan.objects.filter(booking=booking).exists())

    def test_offline_sync_records_gate(self):
        booking = book(self.visitor, self.museum, visit_date=self.today, qty=2, confirm=True)
        r = self.client.post("/api/bookings/checkin-sync/", {"museum": self.museum.slug, "gate": self.west.id, "entries": [
            {"reference": booking.reference, "checked_in_at": timezone.now().isoformat(), "scan_id": "g-1"}]}, format="json")
        self.assertEqual(r.data["results"][0]["result"], "ok")
        self.assertEqual(GateScan.objects.get(scan_id="g-1").gate, self.west)

    def test_manifest_lists_active_gates(self):
        self.west.is_active = False
        self.west.save()
        r = self.client.get("/api/bookings/gate-manifest/", {"museum": self.museum.slug})
        self.assertEqual(r.data["gates"], [{"id": self.east.id, "name": "East"}])

    def test_gates_api(self):
        r = self.client.get("/api/admin/gates/", {"museum": self.museum.slug})
        self.assertEqual([g["name"] for g in r.data], ["East", "West"])
        self.assertEqual(self.client.post("/api/admin/gates/", {"museum": self.museum.slug, "name": "South"}).status_code, 403)
        admin = client_for(make_admin())
        r = admin.post("/api/admin/gates/", {"museum": self.museum.slug, "name": "South"}, format="json")
        self.assertEqual(r.status_code, 201, r.data)
        other_staff = client_for(make_staff(make_museum()))
        self.assertEqual(other_staff.get("/api/admin/gates/", {"museum": self.museum.slug}).data, [])


class OccupancyTests(APITestCase):
    def setUp(self):
        super().setUp()
        self.today = timezone.localdate()
        self.museum = make_museum(slots=[
            (datetime.time(9), datetime.time(10), 50),
            (datetime.time(10), datetime.time(11), 50),
            (datetime.time(11), datetime.time(12), 50),
        ])
        self.museum.closing_time = datetime.time(18)
        self.museum.save()
        self.gate = Gate.objects.create(museum=self.museum, name="Main")
        self.staff = make_staff(self.museum)
        self.client = client_for(self.staff)
        self.visitor = make_visitor()
        self.slots = list(self.museum.slots.order_by("start_time"))

    def test_counts_and_estimate(self):
        b1 = book(self.visitor, self.museum, slot=self.slots[0], visit_date=self.today, qty=4, confirm=True)
        b2 = book(self.visitor, self.museum, slot=self.slots[1], visit_date=self.today, qty=3, confirm=True)
        b3 = book(self.visitor, self.museum, slot=self.slots[2], visit_date=self.today, qty=5, confirm=True)
        from bookings import services as booking_services

        booking_services.mark_checked_in(b1, self.staff)  # no gate recorded
        booking_services.mark_checked_in(b2, self.staff)
        GateScan.objects.filter(booking=b2).update(gate=self.gate)
        booking_services.mark_checked_in(b3, self.staff, admitted=2)
        GateScan.objects.filter(booking=b3).update(gate=self.gate)
        with frozen_now(at(self.today, 11, 30)):
            r = self.client.get("/api/admin/occupancy/", {"museum": self.museum.slug})
        self.assertEqual(r.status_code, 200, r.data)
        t = r.data["totals"]
        self.assertEqual(t["expected"], 12)
        self.assertEqual(t["entered"], 9)
        self.assertEqual(t["inside_estimate"], 5)  # slots 10:00 (3) + 11:00 (2)
        self.assertEqual(t["inside_capacity"], 100)
        self.assertEqual(t["inside_pct"], 5)
        current = [s for s in r.data["slots"] if s["is_current"]]
        self.assertEqual(len(current), 1)
        main = next(g for g in r.data["gates"] if g["gate_id"] == self.gate.id)
        self.assertEqual(main["entered"], 5)
        unknown = next(g for g in r.data["gates"] if g["gate_id"] is None)
        self.assertEqual(unknown["entered"], 4)
        with frozen_now(at(self.today, 19)):  # after closing
            r = self.client.get("/api/admin/occupancy/", {"museum": self.museum.slug})
        self.assertEqual(r.data["totals"]["inside_estimate"], 0)

    def test_pass_entries_counted(self):
        other = make_museum()
        combo = make_pass(self.museum, other)
        order = buy(self.visitor, combo, indian=2)
        PassVisit.objects.create(order=order, museum=self.museum, visited_at=at(self.today, 10, 15), admitted=2, gate=self.gate)
        with frozen_now(at(self.today, 10, 30)):
            r = self.client.get("/api/admin/occupancy/", {"museum": self.museum.slug})
        self.assertEqual(r.data["totals"]["pass_expected"], 2)
        self.assertEqual(r.data["totals"]["entered"], 2)
        self.assertEqual(r.data["slots"][1]["pass_entered"], 2)
        self.assertEqual(r.data["totals"]["inside_estimate"], 2)

    def test_staff_scope(self):
        outsider = client_for(make_staff(make_museum()))
        self.assertEqual(outsider.get("/api/admin/occupancy/", {"museum": self.museum.slug}).status_code, 403)
        self.assertEqual(client_for(self.visitor).get("/api/admin/occupancy/").status_code, 403)


class AdminPassTests(APITestCase):
    def setUp(self):
        super().setUp()
        self.m1 = make_museum()
        self.m2 = make_museum()
        self.admin = client_for(make_admin())

    def test_crud(self):
        data = {"name": "Golden Triangle", "description": "x", "validity_days": 2, "price_indian": "150",
                "price_foreign": "2000", "price_student": "75", "price_child": "0",
                "museum_slugs": [self.m2.slug, self.m1.slug]}
        r = self.admin.post("/api/admin/passes/", data, format="json")
        self.assertEqual(r.status_code, 201, r.data)
        self.assertEqual(r.data["slug"], "golden-triangle")
        self.assertEqual([s["slug"] for s in r.data["sites"]], [self.m2.slug, self.m1.slug])
        pid = r.data["id"]
        r = self.admin.patch(f"/api/admin/passes/{pid}/", {"museum_slugs": [self.m1.slug, self.m2.slug], "featured": True}, format="json")
        self.assertEqual(r.status_code, 200, r.data)
        self.assertEqual([s["slug"] for s in r.data["sites"]], [self.m1.slug, self.m2.slug])
        self.assertEqual(self.admin.post("/api/admin/passes/", {**data, "museum_slugs": [self.m1.slug]}, format="json").status_code, 400)
        # Bought passes can't be deleted
        buy(make_visitor(), ComboPass.objects.get(pk=pid))
        self.assertEqual(self.admin.delete(f"/api/admin/passes/{pid}/").status_code, 400)
        self.assertEqual(self.admin.get("/api/admin/pass-orders/").data["count"], 1)

    def test_admin_only(self):
        self.assertEqual(client_for(make_staff(self.m1)).get("/api/admin/passes/").status_code, 403)
        self.assertEqual(client_for(make_visitor()).get("/api/admin/pass-orders/").status_code, 403)
