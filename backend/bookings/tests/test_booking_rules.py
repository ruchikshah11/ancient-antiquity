"""Online, group and counter booking rules; seat holds; demo payment; cancellation and refund policy."""
import datetime
from decimal import Decimal

from django.conf import settings
from django.test import override_settings
from django.utils import timezone
from rest_framework.exceptions import ValidationError

from bookings import services
from bookings.models import Booking
from bookings.tests.factories import (
    ALL_DAY, APITestCase, add_slot, age_booking, at, book, booking_payload, client_for, first_slot, frozen_now,
    future_open_date, make_admin, make_museum, make_staff, make_visitor, ticket,
)

NO_RAZORPAY = override_settings(RAZORPAY_KEY_ID="", RAZORPAY_KEY_SECRET="", RAZORPAY_WEBHOOK_SECRET="")


@NO_RAZORPAY
class OnlineBookingTests(APITestCase):
    url = "/api/bookings/"

    def setUp(self):
        super().setUp()
        self.museum = make_museum(closed_weekday=0)
        self.slot = first_slot(self.museum)
        self.day = future_open_date(self.museum)
        self.visitor = make_visitor()
        self.client = client_for(self.visitor)

    def post(self, **overrides):
        payload = booking_payload(self.museum, self.slot, self.day, qty=2)
        payload.update(overrides)
        return self.client.post(self.url, payload, format="json")

    def test_create_pending_booking_with_hold(self):
        r = self.post()
        self.assertEqual(r.status_code, 201, r.data)
        self.assertEqual(r.data["status"], "pending")
        self.assertEqual(Decimal(r.data["total_amount"]), Decimal("100.00"))
        self.assertEqual(r.data["total_visitors"], 2)
        self.assertIsNotNone(r.data["hold_expires_at"])
        self.assertTrue(r.data["reference"].startswith("AA-"))

    def test_requires_login(self):
        r = client_for().post(self.url, booking_payload(self.museum, self.slot, self.day), format="json")
        self.assertEqual(r.status_code, 401)

    def test_max_tickets_per_booking(self):
        r = self.post(items=[{"ticket_type": ticket(self.museum).id, "quantity": settings.MAX_TICKETS_PER_BOOKING + 1}])
        self.assertEqual(r.status_code, 400)
        self.assertIn("Maximum 20", str(r.data["items"]))
        r = self.post(items=[{"ticket_type": ticket(self.museum).id, "quantity": 20}])
        self.assertEqual(r.status_code, 201)

    def test_zero_tickets_rejected(self):
        r = self.post(items=[{"ticket_type": ticket(self.museum).id, "quantity": 0}])
        self.assertEqual(r.status_code, 400)

    def test_date_rules(self):
        today = timezone.localdate()
        past = self.post(visit_date=str(today - datetime.timedelta(days=1)))
        self.assertIn("visit_date", past.data)
        too_far = self.post(visit_date=str(today + datetime.timedelta(days=settings.BOOKING_WINDOW_DAYS + 1)))
        self.assertIn("visit_date", too_far.data)
        monday = self.day + datetime.timedelta(days=(0 - self.day.weekday()) % 7)
        closed = self.post(visit_date=str(monday))
        self.assertEqual(closed.status_code, 400)
        self.assertIn("closed", str(closed.data["visit_date"]))

    def test_slot_and_ticket_must_belong_to_the_place(self):
        other = make_museum()
        r = self.post(slot=first_slot(other).id)
        self.assertIn("slot", r.data)
        r = self.post(items=[{"ticket_type": ticket(other).id, "quantity": 1}])
        self.assertIn("items", r.data)

    def test_slot_already_started_today(self):
        day = future_open_date(self.museum, 2)
        with frozen_now(at(day, 10, 30)):
            r = self.post(visit_date=str(day))
            self.assertEqual(r.status_code, 400)
            self.assertIn("already started", str(r.data["slot"]))
            later = self.museum.slots.order_by("start_time").last()
            self.assertEqual(self.post(visit_date=str(day), slot=later.id).status_code, 201)

    def test_capacity_cannot_be_oversold(self):
        small = make_museum(slots=[(datetime.time(10), datetime.time(11), 5)])
        slot = first_slot(small)
        r1 = self.client.post(self.url, booking_payload(small, slot, self.day, qty=3), format="json")
        r2 = self.client.post(self.url, booking_payload(small, slot, self.day, qty=2), format="json")
        self.assertEqual((r1.status_code, r2.status_code), (201, 201))
        r3 = self.client.post(self.url, booking_payload(small, slot, self.day, qty=1), format="json")
        self.assertEqual(r3.status_code, 400)
        self.assertIn("Only 0", str(r3.data["slot"]))
        self.assertEqual(Booking.objects.filter(slot=slot).count(), 2)
        # another day is unaffected
        other_day = self.client.post(self.url, booking_payload(small, slot, self.day + datetime.timedelta(days=1)), format="json")
        self.assertEqual(other_day.status_code, 201)

    def test_free_tickets_confirm_immediately(self):
        free = make_museum(tickets=[("Child", "0.00")])
        r = self.client.post(self.url, booking_payload(free, first_slot(free), self.day, ticket_name="Child"), format="json")
        self.assertEqual(r.data["status"], "confirmed")
        self.assertEqual(r.data["payment_method"], "free")

    def test_visitor_sees_only_own_bookings(self):
        mine = book(self.visitor, self.museum)
        theirs = book(make_visitor(), self.museum)
        r = self.client.get(self.url)
        refs = {b["reference"] for b in r.data["results"]}
        self.assertEqual(refs, {mine.reference})
        self.assertEqual(self.client.get(f"{self.url}{theirs.reference}/").status_code, 404)
        self.assertEqual(self.client.post(f"{self.url}{theirs.reference}/pay/", {"method": "upi"}).status_code, 404)


@NO_RAZORPAY
class SeatHoldTests(APITestCase):
    def setUp(self):
        super().setUp()
        self.museum = make_museum(slots=[(datetime.time(10), datetime.time(11), 4)])
        self.slot = first_slot(self.museum)
        self.day = future_open_date(self.museum)
        self.visitor = make_visitor()

    def test_expired_hold_releases_seats(self):
        held = book(self.visitor, self.museum, qty=4)
        with self.assertRaises(ValidationError):
            book(make_visitor(), self.museum, qty=1)
        age_booking(held, settings.BOOKING_HOLD_MINUTES + 1)
        late = book(make_visitor(), self.museum, qty=4)
        self.assertEqual(late.status, Booking.Status.PENDING)
        services.expire_stale_bookings()
        held.refresh_from_db()
        self.assertEqual(held.status, Booking.Status.EXPIRED)

    def test_expired_booking_cannot_be_paid(self):
        held = age_booking(book(self.visitor, self.museum, qty=1), settings.BOOKING_HOLD_MINUTES + 1)
        r = client_for(self.visitor).post(f"/api/bookings/{held.reference}/pay/", {"method": "upi"})
        self.assertEqual(r.status_code, 400)
        held.refresh_from_db()
        self.assertEqual(held.status, Booking.Status.EXPIRED)

    def test_pay_by_holds_seats_until_deadline(self):
        held = book(self.visitor, self.museum, qty=4)
        Booking.objects.filter(pk=held.pk).update(
            created_at=timezone.now() - datetime.timedelta(days=2), pay_by=timezone.now() + datetime.timedelta(days=1)
        )
        services.expire_stale_bookings()
        held.refresh_from_db()
        self.assertEqual(held.status, Booking.Status.PENDING)
        self.assertEqual(services.booked_visitors_by_slot(self.museum, self.day), {self.slot.id: 4})

        Booking.objects.filter(pk=held.pk).update(pay_by=timezone.now() - datetime.timedelta(minutes=1))
        services.expire_stale_bookings()
        held.refresh_from_db()
        self.assertEqual(held.status, Booking.Status.EXPIRED)
        self.assertEqual(services.booked_visitors_by_slot(self.museum, self.day), {})


@NO_RAZORPAY
class MockPaymentTests(APITestCase):
    def setUp(self):
        super().setUp()
        self.museum = make_museum()
        self.visitor = make_visitor()
        self.booking = book(self.visitor, self.museum, qty=2)
        self.client = client_for(self.visitor)

    def test_payment_order_reports_mock_gateway(self):
        r = self.client.post(f"/api/bookings/{self.booking.reference}/payment-order/")
        self.assertEqual(r.data, {"provider": "mock"})
        self.assertEqual(client_for().get("/api/payments/config/").data["provider"], "mock")

    def test_pay_confirms(self):
        r = self.client.post(f"/api/bookings/{self.booking.reference}/pay/", {"method": "card"})
        self.assertEqual(r.status_code, 200, r.data)
        self.assertEqual(r.data["status"], "confirmed")
        self.assertEqual(r.data["payment_method"], "card")
        self.assertTrue(r.data["payment_id"].startswith("MOCK-"))
        self.assertEqual(r.data["gateway"], "mock")
        # paying twice is refused
        again = self.client.post(f"/api/bookings/{self.booking.reference}/pay/", {"method": "card"})
        self.assertEqual(again.status_code, 400)

    def test_cash_not_allowed_online(self):
        r = self.client.post(f"/api/bookings/{self.booking.reference}/pay/", {"method": "cash"})
        self.assertEqual(r.status_code, 400)


@NO_RAZORPAY
class GroupBookingTests(APITestCase):
    url = "/api/bookings/group/"

    def setUp(self):
        super().setUp()
        self.museum = make_museum()  # slots of 100 -> groups may take 30 per slot
        self.slot = first_slot(self.museum)
        self.day = future_open_date(self.museum)
        self.client = client_for(make_visitor())

    def post(self, qty, group_type="school", escorts=0, items=None, **extra):
        payload = booking_payload(self.museum, self.slot, self.day, qty=qty, group_type=group_type,
                                  organisation_name="DPS Jaipur", escort_count=escorts, **extra)
        if items is not None:
            payload["items"] = items
        return self.client.post(self.url, payload, format="json")

    def test_minimum_size(self):
        r = self.post(20)
        self.assertEqual(r.status_code, 400)
        self.assertIn("21", str(r.data["items"]))

    def test_maximum_size(self):
        adult, foreign = ticket(self.museum), ticket(self.museum, "Foreign national")
        r = self.post(0, items=[{"ticket_type": adult.id, "quantity": 31}, {"ticket_type": foreign.id, "quantity": 30}])
        self.assertEqual(r.status_code, 400)
        self.assertIn("Maximum 60", str(r.data["items"]))

    def test_school_discount_and_escorts(self):
        r = self.post(25, escorts=3)  # ceil(25/10) = 3 escorts allowed
        self.assertEqual(r.status_code, 201, r.data)
        self.assertTrue(r.data["is_group"])
        self.assertEqual(r.data["total_visitors"], 28)
        self.assertEqual(Decimal(r.data["subtotal_amount"]), Decimal("1250.00"))
        self.assertEqual(Decimal(r.data["discount_amount"]), Decimal("313.00"))  # 25% of 1250 = 312.5 -> 313
        self.assertEqual(Decimal(r.data["total_amount"]), Decimal("937.00"))

    def test_too_many_escorts(self):
        r = self.post(25, escorts=4)
        self.assertEqual(r.status_code, 400)
        self.assertIn("Up to 3", str(r.data["escort_count"]))

    def test_escorts_only_for_schools_and_colleges(self):
        r = self.post(25, group_type="tour_operator", escorts=1)
        self.assertEqual(r.status_code, 400)
        self.assertIn("only for school", str(r.data["escort_count"]))
        self.assertEqual(self.post(21, group_type="college", escorts=3).status_code, 201)

    def test_other_groups_get_ten_percent(self):
        r = self.post(24, group_type="corporate")
        self.assertEqual(r.status_code, 201, r.data)
        self.assertEqual(Decimal(r.data["discount_amount"]), Decimal("120.00"))
        self.assertEqual(Decimal(r.data["total_amount"]), Decimal("1080.00"))

    def test_groups_capped_at_slot_share(self):
        self.assertEqual(self.post(28, group_type="tour_operator").status_code, 201)
        r = self.post(21, group_type="tour_operator")
        self.assertEqual(r.status_code, 400)
        self.assertIn("room for 2 more", str(r.data["slot"]))
        # individuals can still book the rest of the slot
        individual = self.client.post("/api/bookings/", booking_payload(self.museum, self.slot, self.day, qty=20), format="json")
        self.assertEqual(individual.status_code, 201)

    def test_place_without_groups(self):
        self.museum.allow_groups = False
        self.museum.save()
        r = self.post(25)
        self.assertEqual(r.status_code, 400)
        self.assertIn("museum", r.data)


@NO_RAZORPAY
class CounterSaleTests(APITestCase):
    url = "/api/bookings/counter/"

    def setUp(self):
        super().setUp()
        self.museum = make_museum(slots=[(*ALL_DAY, 50)])
        self.slot = first_slot(self.museum)
        self.staff = make_staff(self.museum)

    def payload(self, **extra):
        return {
            "museum": self.museum.slug, "slot": self.slot.id, "payment_method": "cash",
            "items": [{"ticket_type": ticket(self.museum).id, "quantity": 3}], **extra,
        }

    def test_sale_is_paid_and_checked_in(self):
        r = client_for(self.staff).post(self.url, self.payload(), format="json")
        self.assertEqual(r.status_code, 201, r.data)
        self.assertEqual(r.data["status"], "checked_in")
        self.assertEqual(r.data["channel"], "counter")
        self.assertEqual(r.data["visit_date"], str(timezone.localdate()))
        self.assertEqual(r.data["visitors_arrived"], 3)
        self.assertEqual(r.data["sold_by_email"], self.staff.email)
        self.assertTrue(r.data["payment_id"].startswith("CTR-"))

    def test_sale_without_check_in(self):
        r = client_for(self.staff).post(self.url, self.payload(check_in=False), format="json")
        self.assertEqual(r.data["status"], "confirmed")
        self.assertEqual(r.data["visitors_arrived"], 0)

    def test_today_only(self):
        tomorrow = timezone.localdate() + datetime.timedelta(days=1)
        r = client_for(self.staff).post(self.url, self.payload(visit_date=str(tomorrow)), format="json")
        self.assertEqual(r.status_code, 400)
        self.assertIn("today", str(r.data["visit_date"]))

    def test_ended_slot_rejected(self):
        today = timezone.localdate()
        with frozen_now(at(today, 12, 0)):
            morning = add_slot(self.museum, datetime.time(9), datetime.time(10), 50)
            r = client_for(self.staff).post(self.url, self.payload(slot=morning.id), format="json")
        self.assertEqual(r.status_code, 400)
        self.assertIn("ended", str(r.data["slot"]))

    def test_only_assigned_panel_users(self):
        self.assertEqual(client_for(make_visitor()).post(self.url, self.payload(), format="json").status_code, 403)
        r = client_for(make_staff(make_museum())).post(self.url, self.payload(), format="json")
        self.assertEqual(r.status_code, 403)


@NO_RAZORPAY
class CancellationTests(APITestCase):
    def setUp(self):
        super().setUp()
        self.museum = make_museum()
        self.visitor = make_visitor()
        self.client = client_for(self.visitor)

    def cancel(self, booking, client=None):
        return (client or self.client).post(f"/api/bookings/{booking.reference}/cancel/")

    def test_full_refund_well_before_visit(self):
        booking = book(self.visitor, self.museum, qty=2, confirm=True)
        self.assertEqual(booking.refundable_amount, Decimal("100.00"))
        r = self.cancel(booking)
        self.assertEqual(r.status_code, 200, r.data)
        self.assertEqual(r.data["status"], "cancelled")
        self.assertEqual(Decimal(r.data["refund_amount"]), Decimal("100.00"))
        self.assertEqual(r.data["refund_status"], "processed")
        self.assertTrue(r.data["refund_id"].startswith("MOCKRF-"))

    def test_refund_boundary_exactly_24_hours(self):
        day = future_open_date(self.museum, 5)
        booking = book(self.visitor, self.museum, visit_date=day, confirm=True)  # 10:00 slot
        with frozen_now(at(day - datetime.timedelta(days=1), 10, 0)):
            r = self.cancel(booking)
        self.assertEqual(Decimal(r.data["refund_amount"]), Decimal("50.00"))

    def test_no_refund_inside_24_hours(self):
        day = future_open_date(self.museum, 5)
        afternoon = self.museum.slots.order_by("start_time").last()  # 14:00
        booking = book(self.visitor, self.museum, slot=afternoon, visit_date=day, confirm=True)
        with frozen_now(at(day, 9, 0)):
            r = self.cancel(booking)
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.data["status"], "cancelled")
        self.assertEqual(Decimal(r.data["refund_amount"]), Decimal("0"))
        self.assertEqual(r.data["refund_status"], "")

    def test_counter_sales_are_not_refunded_online(self):
        museum = make_museum(slots=[(*ALL_DAY, 50)])
        staff = make_staff(museum)
        booking = book(staff, museum, visit_date=future_open_date(museum, 3), channel=Booking.Channel.COUNTER,
                       payment_method=Booking.PaymentMethod.CASH)
        self.assertEqual(booking.status, Booking.Status.CONFIRMED)
        r = self.cancel(booking, client_for(staff))
        self.assertEqual(r.status_code, 200, r.data)
        self.assertEqual(Decimal(r.data["refund_amount"]), Decimal("0"))

    def test_pending_cancel_has_no_refund_and_frees_seats(self):
        booking = book(self.visitor, self.museum, qty=2)
        r = self.cancel(booking)
        self.assertEqual(r.data["status"], "cancelled")
        self.assertEqual(Decimal(r.data["refund_amount"]), Decimal("0"))
        self.assertEqual(services.booked_visitors_by_slot(self.museum, booking.visit_date), {})

    def test_cannot_cancel_twice_or_after_visit(self):
        booking = book(self.visitor, self.museum, confirm=True)
        self.cancel(booking)
        self.assertEqual(self.cancel(booking).status_code, 400)
        past = book(self.visitor, self.museum, visit_date=timezone.localdate() - datetime.timedelta(days=1), confirm=True)
        self.assertEqual(self.cancel(past).status_code, 400)


@NO_RAZORPAY
class GroupSwitchTests(APITestCase):
    """Admin -> Settings switches and each place's allow_groups both gate group bookings."""

    url = "/api/bookings/group/"

    def setUp(self):
        super().setUp()
        from museums.models import SiteSettings

        self.museum = make_museum()
        self.slot = first_slot(self.museum)
        self.day = future_open_date(self.museum)
        self.client = client_for(make_visitor())
        self.admin = client_for(make_admin())
        SiteSettings.load()  # row exists

    def post(self):
        payload = booking_payload(self.museum, self.slot, self.day, qty=25, group_type="school", organisation_name="DPS")
        return self.client.post(self.url, payload, format="json")

    def test_site_wide_switch_pauses_groups_everywhere_with_message(self):
        r = self.admin.patch("/api/admin/site-settings/", {"group_bookings_enabled": False,
                                                            "paused_message": "Paused for Diwali week"}, format="json")
        self.assertEqual(r.status_code, 200, r.data)
        refused = self.post()
        self.assertEqual(refused.status_code, 400)
        self.assertIn("Paused for Diwali week", str(refused.data))
        detail = client_for().get(f"/api/museums/{self.museum.slug}/").data
        self.assertEqual((detail["groups_open"], detail["allow_groups"]), (False, True))  # the place's own setting is untouched
        self.assertEqual(detail["groups_paused_message"], "Paused for Diwali week")
        self.assertTrue(detail["group_requests_open"])  # only the switched-off kind is paused
        self.admin.patch("/api/admin/site-settings/", {"group_bookings_enabled": True}, format="json")
        self.assertEqual(self.post().status_code, 201)

    def test_one_place_can_stop_groups(self):
        self.museum.allow_groups = False
        self.museum.save()
        self.assertEqual(self.post().status_code, 400)
        other = make_museum()
        self.assertTrue(client_for().get(f"/api/museums/{other.slug}/").data["groups_open"])

    def test_only_admins_change_settings(self):
        self.assertEqual(self.client.patch("/api/admin/site-settings/", {"group_bookings_enabled": False}, format="json").status_code, 403)
        self.assertEqual(client_for(make_staff(self.museum)).get("/api/admin/site-settings/").status_code, 403)
        self.assertTrue(client_for().get("/api/site-settings/").data["group_bookings_enabled"])


class FooterSettingsTests(APITestCase):
    """Admin -> Settings footer texts: admins edit them, everyone can read them; empty = standard wording."""

    def test_admin_edits_footer_and_public_sees_it(self):
        admin = client_for(make_admin())
        r = admin.patch("/api/admin/site-settings/", {"footer_brand": "Ancient Antiquity",
                                                       "footer_copyright": "© {year} Ancient Antiquity Heritage Pvt. Ltd."}, format="json")
        self.assertEqual(r.status_code, 200, r.data)
        public = client_for().get("/api/site-settings/").data
        self.assertEqual(public["footer_copyright"], "© {year} Ancient Antiquity Heritage Pvt. Ltd.")
        self.assertEqual(public["footer_tagline"], "")  # not set: the site keeps its translated wording
        self.assertEqual(client_for(make_visitor()).patch("/api/admin/site-settings/", {"footer_brand": "x"}, format="json").status_code, 403)
