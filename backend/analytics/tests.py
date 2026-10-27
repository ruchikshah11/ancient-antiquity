import datetime
from io import StringIO

from django.core import mail
from django.core.management import call_command
from django.utils import timezone

from bookings.models import Booking
from bookings.tests.factories import (
    APITestCase, age_booking, book, client_for, first_slot, make_admin, make_museum, make_staff, make_visitor,
)
from notifications.models import NotificationLog

from .models import EmailOptOut, FunnelEvent, RecoveryEmail
from .recovery import candidates, unsubscribe_token

EVENTS = "/api/analytics/events/"
FUNNEL = "/api/admin/funnel/"
BROWSER = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/130"
SESSION = "sess_abcdef123456"


def send_events(user=None, events=(), session=SESSION, ua=BROWSER, **extra):
    return client_for(user).post(EVENTS, {"session_id": session, "events": list(events), **extra}, format="json",
                                 HTTP_USER_AGENT=ua)


class FunnelEventTests(APITestCase):
    def setUp(self):
        super().setUp()
        self.museum = make_museum()

    def test_records_batch_dedupes_and_links_own_booking_only(self):
        me, other = make_visitor(), make_visitor()
        mine, theirs = book(me, self.museum), book(other, self.museum)
        r = send_events(me, [
            {"event": "view_place", "museum": self.museum.slug},
            {"event": "view_place", "museum": self.museum.slug},  # duplicate
            {"event": "select_slot", "museum": self.museum.slug},
            {"event": "view_checkout", "booking": mine.reference},
            {"event": "view_checkout", "booking": theirs.reference},  # not linked
            {"event": "hack"},
        ], utm={"source": "recovery", "medium": "email"})
        self.assertEqual(r.status_code, 202)
        self.assertEqual(r.data["recorded"], 4)
        checkout = FunnelEvent.objects.filter(event="view_checkout")
        self.assertEqual(sorted(str(e.booking_id) for e in checkout), sorted([str(mine.id), "None"]))
        self.assertEqual(checkout.get(booking=mine).museum_id, self.museum.id)
        self.assertEqual(FunnelEvent.objects.filter(utm_source="recovery").count(), 4)

    def test_ignores_bots_staff_and_bad_sessions(self):
        ev = [{"event": "view_place", "museum": self.museum.slug}]
        self.assertEqual(send_events(None, ev, ua="Googlebot/2.1").data["recorded"], 0)
        self.assertEqual(send_events(None, ev, ua="").data["recorded"], 0)
        self.assertEqual(send_events(make_staff(self.museum), ev).data["recorded"], 0)
        self.assertEqual(send_events(make_admin(), ev).data["recorded"], 0)
        self.assertEqual(send_events(None, ev, session="x").data["recorded"], 0)
        self.assertEqual(send_events(None, ev).data["recorded"], 1)
        self.assertEqual(FunnelEvent.objects.count(), 1)


class FunnelReportTests(APITestCase):
    def setUp(self):
        super().setUp()
        self.a, self.b = make_museum("Alpha Fort"), make_museum("Beta Palace")
        for i in range(4):
            send_events(None, [{"event": "view_place", "museum": self.a.slug}], session=f"session_a_{i}")
        send_events(None, [{"event": "select_slot", "museum": self.a.slug}], session="session_a_0")
        send_events(None, [{"event": "view_place", "museum": self.b.slug}], session="session_b_0")
        visitor = make_visitor()
        book(visitor, self.a, confirm=True)
        cancelled = book(visitor, self.a, confirm=True)
        Booking.objects.filter(pk=cancelled.pk).update(status=Booking.Status.CANCELLED)
        book(visitor, self.b)  # started, unpaid

    def test_admin_report(self):
        r = client_for(make_admin()).get(FUNNEL)
        self.assertEqual(r.status_code, 200, r.data)
        steps = {s["key"]: s for s in r.data["steps"]}
        self.assertEqual(steps["view_place"]["count"], 5)
        self.assertEqual(steps["select_slot"]["count"], 1)
        self.assertEqual(steps["start_booking"]["count"], 3)
        self.assertEqual(steps["paid"]["count"], 2)  # the cancelled one was paid first
        self.assertEqual(steps["select_slot"]["pct_of_previous"], 20.0)
        self.assertEqual(r.data["cancelled"], 1)
        top = r.data["top_places"]
        self.assertEqual(top[0]["slug"], self.a.slug)
        self.assertEqual((top[0]["views"], top[0]["paid"], top[0]["conversion"]), (4, 2, 50.0))
        self.assertEqual(len(r.data["daily"]), 30)
        self.assertEqual(r.data["recovery"], {"sent": 0, "converted": 0, "conversion": None})

    def test_staff_scoped_to_their_places(self):
        staff = make_staff(self.b)
        r = client_for(staff).get(FUNNEL)
        steps = {s["key"]: s["count"] for s in r.data["steps"]}
        self.assertEqual((steps["view_place"], steps["start_booking"], steps["paid"]), (1, 1, 0))
        self.assertEqual(client_for(staff).get(FUNNEL, {"museum": self.a.slug}).status_code, 403)
        self.assertEqual(client_for(make_visitor()).get(FUNNEL).status_code, 403)
        self.assertEqual(client_for().get(FUNNEL).status_code, 401)


class RecoveryTests(APITestCase):
    def setUp(self):
        super().setUp()
        self.museum = make_museum("Amber Fort")
        self.visitor = make_visitor(first_name="Asha")

    def abandoned(self, minutes=60, user=None, **kw):
        booking = age_booking(book(user or self.visitor, self.museum, **kw), minutes)
        Booking.objects.filter(pk=booking.pk).update(status=Booking.Status.EXPIRED)
        booking.refresh_from_db()
        return booking

    def run_command(self):
        out = StringIO()
        call_command("send_recovery_emails", stdout=out)
        return out.getvalue()

    def test_sends_once_with_prefilled_link_and_opt_out(self):
        booking = self.abandoned()
        self.assertIn("1 sent", self.run_command())
        self.assertEqual(len(mail.outbox), 1)
        msg = mail.outbox[0]
        self.assertEqual(msg.subject, "Your tickets for Amber Fort are waiting")
        self.assertIn(f"/museums/{self.museum.slug}?date={booking.visit_date.isoformat()}&slot={booking.slot_id}", msg.body)
        self.assertIn("/api/analytics/unsubscribe/", msg.body)
        self.assertIn("List-Unsubscribe", msg.extra_headers)
        self.assertTrue(RecoveryEmail.objects.filter(booking=booking).exists())
        self.assertTrue(NotificationLog.objects.filter(kind="recovery", status="sent").exists())
        self.run_command()  # re-running sends nothing new
        self.assertEqual(len(mail.outbox), 1)

    def test_skips_too_new_too_old_paid_later_and_opted_out(self):
        self.abandoned(minutes=10)                       # too recent
        self.abandoned(minutes=60 * 25)                  # too old
        later = self.abandoned(user=make_visitor())      # but then paid for the same place/date
        book(later.user, self.museum, visit_date=later.visit_date, confirm=True)
        opted = self.abandoned(user=make_visitor())
        EmailOptOut.objects.create(email=opted.visitor_email.upper())
        no_email = self.abandoned(user=make_visitor())
        Booking.objects.filter(pk=no_email.pk).update(visitor_email="")
        no_email.user.email = ""
        no_email.user.save(update_fields=["email"])
        self.assertEqual(list(candidates()), [])

    def test_unsubscribe_link(self):
        token = unsubscribe_token("Asha@Example.com")
        r = self.client.get(f"/api/analytics/unsubscribe/{token}/")
        self.assertEqual(r.status_code, 200)
        self.assertTrue(EmailOptOut.is_opted_out("asha@example.com"))
        self.assertEqual(self.client.get("/api/analytics/unsubscribe/forged:token/").status_code, 400)
        self.assertEqual(self.client.post(f"/api/analytics/unsubscribe/{token}/").status_code, 200)

    def test_conversion_counted_in_funnel(self):
        booking = self.abandoned()
        self.run_command()
        book(self.visitor, self.museum, slot=first_slot(self.museum), visit_date=booking.visit_date, confirm=True)
        r = client_for(make_admin()).get(FUNNEL)
        self.assertEqual(r.data["recovery"], {"sent": 1, "converted": 1, "conversion": 100.0})
        self.assertIsNotNone(RecoveryEmail.objects.get().converted_booking)
        self.assertGreaterEqual(timezone.now(), RecoveryEmail.objects.get().sent_at - datetime.timedelta(seconds=1))
