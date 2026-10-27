"""Events & shows (sessions, event tickets through the normal booking flow) and the waitlist."""
import datetime
from decimal import Decimal
from io import StringIO

from django.core import mail
from django.core.management import call_command
from django.utils import timezone

from bookings import services as booking_services
from bookings.models import Booking
from bookings.tests.factories import (
    APITestCase, PHONE, age_booking, at, book, client_for, first_slot, frozen_now, future_open_date, make_admin,
    make_museum, make_staff, make_visitor,
)
from notifications.models import NotificationLog

from . import services
from .models import Event, EventPrice, EventSession, WaitlistEntry


def make_event(museum, *, title="Light & Sound", kind=Event.Kind.LIGHT_SOUND, days_ahead=10, capacity=50,
               start=datetime.time(19, 0), end=datetime.time(20, 0), prices=(("Adult", "100"), ("Child", "40"))):
    event = Event.objects.create(museum=museum, title=title, kind=kind, description="A show.")
    for i, (name, price) in enumerate(prices):
        EventPrice.objects.create(event=event, name=name, price=Decimal(price), sort=i)
    session = EventSession.objects.create(
        event=event, date=timezone.localdate() + datetime.timedelta(days=days_ahead),
        start_time=start, end_time=end, capacity=capacity,
    )
    return event, session


def event_payload(session, qty=2, price=None, **extra):
    price = price or session.event.prices.first()
    return {
        "session": session.id,
        "items": [{"price": price.id, "quantity": qty}],
        "visitor_name": "Asha Rao",
        "visitor_email": "asha@example.com",
        "visitor_phone": PHONE,
        **extra,
    }


def book_event(user, session, qty=2, confirm=False):
    booking = services.create_event_booking(
        user=user, session=session, items=[{"price": session.event.prices.first(), "quantity": qty}],
        visitor_name="Asha Rao", visitor_email=user.email, visitor_phone=PHONE,
    )
    if confirm:
        booking_services.confirm_payment(booking, Booking.PaymentMethod.UPI)
    booking.refresh_from_db()
    return booking


class PublicEventTests(APITestCase):
    def setUp(self):
        super().setUp()
        self.museum = make_museum(name="Red Fort")
        self.event, self.session = make_event(self.museum)

    def test_list_and_filters(self):
        other = make_museum()
        make_event(other, title="Heritage walk", kind=Event.Kind.HERITAGE_WALK)
        res = client_for().get("/api/events/")
        self.assertEqual(res.status_code, 200)
        self.assertEqual(len(res.data), 2)
        res = client_for().get("/api/events/", {"museum": self.museum.slug})
        self.assertEqual([e["slug"] for e in res.data], [self.event.slug])
        self.assertEqual(res.data[0]["from_price"], "40.00")
        self.assertEqual(res.data[0]["upcoming_sessions"], 1)
        res = client_for().get("/api/events/", {"kind": "heritage_walk"})
        self.assertEqual([e["title"] for e in res.data], ["Heritage walk"])
        res = client_for().get("/api/events/", {"state": self.museum.city.state_id})
        self.assertEqual([e["slug"] for e in res.data], [self.event.slug])

    def test_events_without_upcoming_sessions_are_hidden(self):
        self.session.date = timezone.localdate() - datetime.timedelta(days=1)
        self.session.save()
        self.assertEqual(client_for().get("/api/events/").data, [])
        res = client_for().get("/api/events/", {"to": str(timezone.localdate() + datetime.timedelta(days=5))})
        self.assertEqual(res.data, [])

    def test_detail_with_sessions_and_availability(self):
        visitor = make_visitor()
        book_event(visitor, self.session, qty=3, confirm=True)
        res = client_for().get(f"/api/events/{self.event.slug}/")
        self.assertEqual(res.status_code, 200)
        self.assertEqual(len(res.data["prices"]), 2)
        (s,) = res.data["sessions"]
        self.assertEqual((s["capacity"], s["available"], s["sold_out"]), (50, 47, False))

    def test_inactive_event_is_404(self):
        self.event.is_active = False
        self.event.save()
        self.assertEqual(client_for().get(f"/api/events/{self.event.slug}/").status_code, 404)


class EventBookingTests(APITestCase):
    def setUp(self):
        super().setUp()
        self.museum = make_museum()
        self.event, self.session = make_event(self.museum, capacity=5)
        self.visitor = make_visitor()
        self.client = client_for(self.visitor)

    def test_login_required(self):
        self.assertEqual(client_for().post("/api/events/bookings/", event_payload(self.session), format="json").status_code, 401)

    def test_book_pay_and_serialise(self):
        res = self.client.post("/api/events/bookings/", event_payload(self.session, qty=2), format="json")
        self.assertEqual(res.status_code, 201, res.data)
        self.assertEqual(res.data["status"], "pending")
        self.assertTrue(res.data["is_event"])
        self.assertEqual(res.data["event_title"], self.event.title)
        self.assertEqual(res.data["event_slug"], self.event.slug)
        self.assertEqual(res.data["slot_start"], "19:00:00")
        self.assertEqual(res.data["total_amount"], "200.00")
        self.assertEqual(res.data["items"][0]["ticket_name"], "Adult")
        ref = res.data["reference"]
        self.assertEqual(self.client.post(f"/api/bookings/{ref}/payment-order/").status_code, 200)
        with self.captureOnCommitCallbacks(execute=True):
            res = self.client.post(f"/api/bookings/{ref}/pay/", {"method": "upi"}, format="json")
        self.assertEqual(res.status_code, 200, res.data)
        self.assertEqual(res.data["status"], "confirmed")
        booking = Booking.objects.get(reference=ref)
        self.assertIsNone(booking.slot_id)
        self.assertEqual(booking.visit_date, self.session.date)
        # Ticket email names the event and the session time.
        self.assertTrue(any(self.event.title in m.body and "19:00" in m.body for m in mail.outbox))
        # My bookings list renders event bookings.
        self.assertEqual(self.client.get("/api/bookings/").status_code, 200)

    def test_capacity_is_per_session_and_separate_from_slots(self):
        book(self.visitor, self.museum, qty=5, confirm=True)  # entry slot bookings don't use session seats
        res = self.client.post("/api/events/bookings/", event_payload(self.session, qty=5), format="json")
        self.assertEqual(res.status_code, 201)
        res = self.client.post("/api/events/bookings/", event_payload(self.session, qty=1), format="json")
        self.assertEqual(res.status_code, 400)
        self.assertIn("Only 0 seat", str(res.data))

    def test_price_of_other_event_rejected(self):
        _, other_session = make_event(make_museum())
        res = self.client.post(
            "/api/events/bookings/",
            event_payload(self.session, price=other_session.event.prices.first()), format="json",
        )
        self.assertEqual(res.status_code, 400)

    def test_started_or_inactive_session_rejected(self):
        self.session.is_active = False
        self.session.save()
        self.assertEqual(self.client.post("/api/events/bookings/", event_payload(self.session), format="json").status_code, 400)

    def test_free_event_confirms_at_once(self):
        event, session = make_event(self.museum, title="Free walk", prices=(("Everyone", "0"),))
        res = self.client.post("/api/events/bookings/", event_payload(session, qty=1), format="json")
        self.assertEqual(res.data["status"], "confirmed")

    def test_cancel_refund_uses_session_start(self):
        booking = book_event(self.visitor, self.session, confirm=True)
        self.assertEqual(booking.refundable_amount, Decimal("200.00"))
        res = self.client.post(f"/api/bookings/{booking.reference}/cancel/")
        self.assertEqual(res.status_code, 200, res.data)
        self.assertEqual(res.data["refund_status"], "processed")
        # Late cancellation (session starts within 24h): no refund.
        _, soon = make_event(self.museum, title="Soon", days_ahead=0, start=datetime.time(23, 0), end=datetime.time(23, 50))
        with frozen_now(at(timezone.localdate(), 9)):
            late = book_event(self.visitor, soon, confirm=True)
            self.assertEqual(late.refundable_amount, 0)

    def test_invoice_and_exports_and_manifest(self):
        staff = make_staff(self.museum)
        booking = book_event(self.visitor, self.session, confirm=True)
        res = self.client.get(f"/api/bookings/{booking.reference}/invoice/")
        self.assertEqual(res.status_code, 200)
        self.assertEqual(str(res.data["slot_start"]), "19:00:00")
        admin = client_for(make_admin())
        res = admin.get("/api/admin/reports/bookings.csv")
        self.assertEqual(res.status_code, 200)
        self.assertIn("19:00-20:00", b"".join(res.streaming_content).decode() if res.streaming else res.content.decode())
        res = client_for(staff).get("/api/bookings/gate-manifest/", {"museum": self.museum.slug, "date": str(self.session.date)})
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.data["tickets"][0]["event_title"], self.event.title)
        self.assertEqual(client_for(staff).get("/api/admin/occupancy/", {"museum": self.museum.slug}).status_code, 200)

    def test_gate_checkin_for_event_ticket(self):
        staff = make_staff(self.museum)
        today = timezone.localdate()
        _, tonight = make_event(self.museum, title="Tonight", days_ahead=0, start=datetime.time(19), end=datetime.time(20))
        with frozen_now(at(today, 9)):
            booking = book_event(self.visitor, tonight, confirm=True)
            res = client_for(staff).post("/api/bookings/checkin/", {"reference": booking.reference}, format="json")
        self.assertEqual(res.status_code, 200, res.data)
        self.assertEqual(res.data["status"], "checked_in")

    def test_late_gateway_payment_checks_session_seats(self):
        booking = book_event(self.visitor, self.session, qty=2)
        age_booking(booking, 30)
        booking_services.expire_stale_bookings()
        with self.captureOnCommitCallbacks(execute=True):
            self.assertTrue(booking_services.seats_free_for(Booking.objects.get(pk=booking.pk)))
        book_event(make_visitor(), self.session, qty=4, confirm=True)
        self.assertFalse(booking_services.seats_free_for(Booking.objects.get(pk=booking.pk)))

    def test_reminder_text_uses_session_time(self):
        from notifications.services import _booking_sms_text

        booking = book_event(self.visitor, self.session, confirm=True)
        self.assertIn("19:00", _booking_sms_text(booking, "reminder"))


class WaitlistTests(APITestCase):
    def setUp(self):
        super().setUp()
        self.museum = make_museum(slots=[(datetime.time(10), datetime.time(11), 4)])
        self.slot = first_slot(self.museum)
        self.day = future_open_date(self.museum)
        self.visitor = make_visitor(phone=PHONE)
        self.client = client_for(self.visitor)

    def join(self, client=None, qty=2, **extra):
        payload = {"museum": self.museum.slug, "slot": self.slot.id, "visit_date": str(self.day), "quantity": qty, **extra}
        return (client or self.client).post("/api/waitlist/", payload, format="json")

    def test_only_when_full(self):
        res = self.join()
        self.assertEqual(res.status_code, 400)
        self.assertIn("still 4 seat", str(res.data))

    def test_join_list_and_leave(self):
        book(make_visitor(), self.museum, slot=self.slot, visit_date=self.day, qty=4, confirm=True)
        res = self.join(notify_channels=["email", "sms"])
        self.assertEqual(res.status_code, 201, res.data)
        self.assertEqual(res.data["status"], "waiting")
        self.assertEqual(res.data["start_time"], "10:00:00")
        again = self.join(qty=3)
        self.assertEqual(again.status_code, 200)  # updates the existing entry
        self.assertEqual(again.data["quantity"], 3)
        self.assertEqual(len(self.client.get("/api/waitlist/").data), 1)
        other = client_for(make_visitor())
        self.assertEqual(other.delete(f"/api/waitlist/{res.data['id']}/").status_code, 404)
        self.assertEqual(self.client.delete(f"/api/waitlist/{res.data['id']}/").status_code, 204)
        self.assertEqual(self.client.get("/api/waitlist/").data, [])

    def test_cancellation_notifies_fifo_entries_that_fit(self):
        holder = make_visitor()
        booking = book(holder, self.museum, slot=self.slot, visit_date=self.day, qty=2, confirm=True)
        book(make_visitor(), self.museum, slot=self.slot, visit_date=self.day, qty=2, confirm=True)
        first = self.join(qty=3).data          # too big for the 2 freed seats
        second_user = make_visitor()
        second = self.join(client_for(second_user), qty=2).data
        third = self.join(client_for(make_visitor()), qty=1).data  # nothing left after the second
        mail.outbox.clear()
        with self.captureOnCommitCallbacks(execute=True):
            booking_services.cancel_booking(booking)
        statuses = dict(WaitlistEntry.objects.values_list("id", "status"))
        self.assertEqual(statuses[first["id"]], "waiting")
        self.assertEqual(statuses[second["id"]], "notified")
        self.assertEqual(statuses[third["id"]], "waiting")
        self.assertTrue(any(second_user.email in m.to and "/museums/" in m.body for m in mail.outbox))
        self.assertTrue(NotificationLog.objects.filter(kind="waitlist", user=second_user).exists())

    def test_channels_respected(self):
        booking = book(make_visitor(), self.museum, slot=self.slot, visit_date=self.day, qty=4, confirm=True)
        self.join(qty=1, notify_channels=["sms"])
        mail.outbox.clear()
        with self.captureOnCommitCallbacks(execute=True):
            booking_services.cancel_booking(booking)
        self.assertFalse(any(self.visitor.email in m.to for m in mail.outbox))
        self.assertTrue(NotificationLog.objects.filter(kind="waitlist", channel="sms").exists())

    def test_expired_holds_notify_waitlist(self):
        pending = book(make_visitor(), self.museum, slot=self.slot, visit_date=self.day, qty=4)
        self.join(qty=2)
        age_booking(pending, 30)
        booking_services.expire_stale_bookings()
        self.assertEqual(WaitlistEntry.objects.get().status, "notified")

    def test_booking_closes_own_entry_and_past_entries_expire(self):
        blocker = book(make_visitor(), self.museum, slot=self.slot, visit_date=self.day, qty=4, confirm=True)
        entry_id = self.join(qty=1).data["id"]
        with self.captureOnCommitCallbacks(execute=True):
            booking_services.cancel_booking(blocker)
        book(self.visitor, self.museum, slot=self.slot, visit_date=self.day, qty=1)
        self.assertEqual(WaitlistEntry.objects.get(pk=entry_id).status, "booked")
        old = WaitlistEntry.objects.create(user=self.visitor, museum=self.museum, slot=self.slot,
                                           visit_date=timezone.localdate() - datetime.timedelta(days=1), quantity=1)
        services.expire_past_entries()
        old.refresh_from_db()
        self.assertEqual(old.status, "expired")

    def test_event_session_waitlist(self):
        _, session = make_event(self.museum, capacity=2)
        booking = book_event(make_visitor(), session, qty=2, confirm=True)
        res = self.client.post("/api/waitlist/", {"event_session": session.id, "quantity": 2}, format="json")
        self.assertEqual(res.status_code, 201, res.data)
        self.assertEqual(res.data["event_title"], session.event.title)
        with self.captureOnCommitCallbacks(execute=True):
            booking_services.cancel_booking(booking)
        self.assertEqual(WaitlistEntry.objects.get().status, "notified")
        self.assertTrue(any("/events/" in m.body for m in mail.outbox))

    def test_slot_xor_session(self):
        _, session = make_event(self.museum)
        res = self.client.post("/api/waitlist/", {"slot": self.slot.id, "event_session": session.id, "quantity": 1,
                                                  "museum": self.museum.slug, "visit_date": str(self.day)}, format="json")
        self.assertEqual(res.status_code, 400)


class AdminEventTests(APITestCase):
    def setUp(self):
        super().setUp()
        self.museum = make_museum()
        self.event, self.session = make_event(self.museum)
        self.admin = client_for(make_admin())

    def test_staff_scoped_read_only(self):
        staff = client_for(make_staff(self.museum))
        make_event(make_museum(), title="Elsewhere")
        res = staff.get("/api/admin/events/")
        self.assertEqual([e["id"] for e in res.data], [self.event.id])
        self.assertEqual(staff.patch(f"/api/admin/events/{self.event.id}/", {"title": "x"}, format="json").status_code, 403)
        self.assertEqual(client_for(make_visitor()).get("/api/admin/events/").status_code, 403)
        res = staff.get("/api/admin/event-sessions/", {"event": self.event.id})
        self.assertEqual(len(res.data), 1)

    def test_admin_crud_and_generate(self):
        res = self.admin.post("/api/admin/events/", {
            "museum": self.museum.slug, "title": "Night viewing", "kind": "night_viewing", "duration_minutes": 90,
        }, format="json")
        self.assertEqual(res.status_code, 201, res.data)
        event_id = res.data["id"]
        self.assertEqual(res.data["slug"], "night-viewing")
        res = self.admin.post("/api/admin/event-prices/", {"event": event_id, "name": "Adult", "price": "150"}, format="json")
        self.assertEqual(res.status_code, 201, res.data)
        start = timezone.localdate() + datetime.timedelta(days=1)
        payload = {"start_date": str(start), "end_date": str(start + datetime.timedelta(days=6)),
                   "start_time": "20:00", "end_time": "21:00", "capacity": 30}
        res = self.admin.post(f"/api/admin/events/{event_id}/generate-sessions/", payload, format="json")
        self.assertEqual(res.data["created"], 7)
        res = self.admin.post(f"/api/admin/events/{event_id}/generate-sessions/", payload, format="json")
        self.assertEqual(res.data["created"], 0)
        bad = self.admin.post("/api/admin/event-sessions/", {"event": event_id, "date": str(start), "start_time": "21:00",
                                                             "end_time": "20:00", "capacity": 5}, format="json")
        self.assertEqual(bad.status_code, 400)

    def test_session_with_bookings_cannot_be_deleted(self):
        book_event(make_visitor(), self.session, confirm=True)
        res = self.admin.delete(f"/api/admin/event-sessions/{self.session.id}/")
        self.assertEqual(res.status_code, 400)
        res = self.admin.get("/api/admin/event-sessions/", {"event": self.event.id})
        self.assertEqual(res.data[0]["booked"], 2)

    def test_seed_events(self):
        make_museum(name="Red Fort").__class__.objects.filter(name="Red Fort").update(slug="red-fort-new-delhi")
        out = StringIO()
        call_command("seed_events", stdout=out)
        event = Event.objects.get(slug="red-fort-light-and-sound")
        self.assertTrue(event.sessions.exists())
        self.assertEqual(event.prices.count(), 3)
        count = event.sessions.count()
        call_command("seed_events", stdout=out)  # idempotent
        self.assertEqual(event.sessions.count(), count)
