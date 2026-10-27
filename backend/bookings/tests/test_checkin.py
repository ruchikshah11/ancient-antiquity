"""Gate check-in: single tickets, groups arriving in parts, offline sync with scan ids, gate manifest."""
import datetime

from django.utils import timezone

from bookings.models import Booking, GateScan
from bookings.tests.factories import (
    ALL_DAY, APITestCase, book, client_for, make_museum, make_staff, make_visitor,
)


class CheckinBase(APITestCase):
    def setUp(self):
        super().setUp()
        self.today = timezone.localdate()
        self.museum = make_museum(slots=[(*ALL_DAY, 200)])  # groups may take 60
        self.staff = make_staff(self.museum)
        self.client = client_for(self.staff)
        self.visitor = make_visitor()

    def ticket_today(self, qty=2, **kw):
        return book(self.visitor, self.museum, visit_date=self.today, qty=qty, confirm=True, **kw)

    def group_today(self, participants=40, escorts=4):
        return book(self.visitor, self.museum, visit_date=self.today, qty=participants, confirm=True,
                    group_type=Booking.GroupType.SCHOOL, organisation_name="DPS", escort_count=escorts)

    def checkin(self, reference, **data):
        return self.client.post("/api/bookings/checkin/", {"reference": reference, **data}, format="json")


class CheckinTests(CheckinBase):
    def test_check_in_admits_everyone(self):
        booking = self.ticket_today(qty=3)
        r = self.checkin(booking.reference.lower(), museum=self.museum.slug)  # references are case-insensitive
        self.assertEqual(r.status_code, 200, r.data)
        self.assertEqual(r.data["status"], "checked_in")
        self.assertEqual(r.data["visitors_arrived"], 3)
        self.assertEqual(GateScan.objects.get(booking=booking).admitted, 3)

    def test_already_checked_in(self):
        booking = self.ticket_today()
        self.checkin(booking.reference)
        r = self.checkin(booking.reference)
        self.assertEqual(r.status_code, 400)
        self.assertIn("Already checked in", str(r.data["reference"]))

    def test_wrong_museum(self):
        other = make_museum()
        other.staff.add(self.staff)
        booking = self.ticket_today()
        r = self.checkin(booking.reference, museum=other.slug)
        self.assertEqual(r.status_code, 400)
        self.assertIn("This ticket is for", str(r.data["reference"]))

    def test_wrong_date(self):
        booking = book(self.visitor, self.museum, visit_date=self.today + datetime.timedelta(days=1), confirm=True)
        r = self.checkin(booking.reference)
        self.assertEqual(r.status_code, 400)
        self.assertIn("not today", str(r.data["reference"]))

    def test_unpaid_or_unknown(self):
        pending = book(self.visitor, self.museum, visit_date=self.today)
        self.assertIn("pending", str(self.checkin(pending.reference).data["reference"]))
        self.assertEqual(self.checkin("AA-NOPE0000").status_code, 400)

    def test_staff_of_another_place_cannot_check_in(self):
        booking = self.ticket_today()
        r = client_for(make_staff(make_museum())).post("/api/bookings/checkin/", {"reference": booking.reference})
        self.assertEqual(r.status_code, 403)
        self.assertEqual(client_for(self.visitor).post("/api/bookings/checkin/", {"reference": booking.reference}).status_code, 403)


class GroupCheckinTests(CheckinBase):
    def test_group_arrives_in_parts(self):
        group = self.group_today()  # 40 students + 4 escorts
        self.assertEqual(group.total_visitors, 44)

        r = self.checkin(group.reference)
        self.assertTrue(r.data["needs_count"])
        group.refresh_from_db()
        self.assertEqual(group.status, Booking.Status.CONFIRMED)

        r = self.checkin(group.reference, arrived=38)
        self.assertEqual(r.status_code, 200, r.data)
        self.assertEqual((r.data["status"], r.data["visitors_arrived"], r.data["remaining_to_enter"]), ("checked_in", 38, 6))

        r = self.checkin(group.reference, arrived=7)
        self.assertEqual(r.status_code, 400)
        self.assertIn("1 to 6", str(r.data["arrived"]))

        r = self.checkin(group.reference, arrived=6)
        self.assertEqual(r.data["remaining_to_enter"], 0)
        self.assertEqual(list(GateScan.objects.filter(booking=group).values_list("admitted", flat=True)), [38, 6])

        r = self.checkin(group.reference, arrived=1)
        self.assertIn("Already checked in", str(r.data["reference"]))

    def test_invalid_count(self):
        group = self.group_today()
        self.assertEqual(self.checkin(group.reference, arrived=0).status_code, 400)
        self.assertEqual(self.checkin(group.reference, arrived="lots").status_code, 400)


class CheckinSyncTests(CheckinBase):
    url = "/api/bookings/checkin-sync/"

    def sync(self, *entries, client=None):
        return (client or self.client).post(self.url, {"museum": self.museum.slug, "entries": list(entries)}, format="json")

    def entry(self, booking, scan_id, **extra):
        return {"reference": booking.reference, "checked_in_at": timezone.now().isoformat(), "scan_id": scan_id, **extra}

    def test_resending_same_scan_is_idempotent(self):
        booking = self.ticket_today(qty=2)
        entry = self.entry(booking, "dev1-0001")
        first = self.sync(entry)
        self.assertEqual(first.data["results"][0]["result"], "ok")
        second = self.sync(entry)
        self.assertEqual(second.data["results"][0]["result"], "ok")
        booking.refresh_from_db()
        self.assertEqual(booking.visitors_arrived, 2)
        scan = GateScan.objects.get(booking=booking)
        self.assertTrue(scan.offline)

    def test_second_device_scan_is_duplicate(self):
        booking = self.ticket_today()
        earlier = self.entry(booking, "dev1-0001")
        earlier["checked_in_at"] = (timezone.now() - datetime.timedelta(minutes=5)).isoformat()
        self.sync(earlier)
        r = self.sync(self.entry(booking, "dev2-0001"))
        self.assertEqual(r.data["results"][0]["result"], "duplicate")
        self.assertEqual(GateScan.objects.filter(booking=booking).count(), 1)

    def test_group_partial_sync_and_over_admit(self):
        group = self.group_today()
        r = self.sync(self.entry(group, "g-1", arrived=20), self.entry(group, "g-2", arrived=30))
        self.assertEqual([x["result"] for x in r.data["results"]], ["ok", "duplicate"])
        self.assertIn("Only 24 of 30", r.data["results"][1]["detail"])
        group.refresh_from_db()
        self.assertEqual(group.visitors_arrived, 44)
        # re-sending both scans changes nothing
        self.sync(self.entry(group, "g-1", arrived=20), self.entry(group, "g-2", arrived=30))
        self.assertEqual(GateScan.objects.filter(booking=group).count(), 2)

    def test_invalid_tickets(self):
        cancelled = self.ticket_today()
        Booking.objects.filter(pk=cancelled.pk).update(status=Booking.Status.CANCELLED)
        elsewhere = book(self.visitor, make_museum(), visit_date=self.today, confirm=True)
        r = self.sync(self.entry(cancelled, "x-1"), self.entry(elsewhere, "x-2"))
        self.assertEqual([x["result"] for x in r.data["results"]], ["invalid", "invalid"])

    def test_unassigned_staff_forbidden(self):
        booking = self.ticket_today()
        r = self.sync(self.entry(booking, "x-1"), client=client_for(make_staff(make_museum())))
        self.assertEqual(r.status_code, 403)


class GateManifestTests(CheckinBase):
    def test_manifest_lists_valid_tickets_for_the_day(self):
        paid = self.ticket_today()
        book(self.visitor, self.museum, visit_date=self.today)  # pending: not valid at the gate
        book(self.visitor, self.museum, visit_date=self.today + datetime.timedelta(days=1), confirm=True)
        r = self.client.get("/api/bookings/gate-manifest/", {"museum": self.museum.slug})
        self.assertEqual(r.status_code, 200)
        self.assertEqual([t["reference"] for t in r.data["tickets"]], [paid.reference])

    def test_manifest_scoped_to_assigned_places(self):
        r = client_for(make_staff(make_museum())).get("/api/bookings/gate-manifest/", {"museum": self.museum.slug})
        self.assertEqual(r.status_code, 403)
        self.assertEqual(self.client.get("/api/bookings/gate-manifest/").status_code, 400)
