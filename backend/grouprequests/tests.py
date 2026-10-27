"""Large group requests (>60 people): validation, planning, approval with held seats, payment, decline, scoping."""
import datetime
import math

from django.test import override_settings
from django.utils import timezone

from bookings import services
from bookings.models import Booking
from bookings.tests.factories import (
    APITestCase, book, booking_payload, client_for, future_open_date, make_museum, make_staff, make_visitor,
)
from grouprequests.models import GroupRequest

URL = "/api/group-requests/"
SLOTS = [
    (datetime.time(9), datetime.time(10), 50),
    (datetime.time(10), datetime.time(11), 50),
    (datetime.time(11), datetime.time(12), 50),
    (datetime.time(14), datetime.time(15), 50),
]


class GroupRequestBase(APITestCase):
    def setUp(self):
        super().setUp()
        self.museum = make_museum(slots=SLOTS)
        self.slots = list(self.museum.slots.order_by("start_time"))
        self.day = future_open_date(self.museum, 10)
        self.visitor = make_visitor()
        self.staff = make_staff(self.museum)

    def payload(self, **extra):
        return {
            "museum": self.museum.slug, "preferred_date": str(self.day), "preferred_time": "any",
            "group_type": "school", "organisation_name": "Kendriya Vidyalaya", "contact_name": "Mrs Iyer",
            "contact_email": "iyer@example.com", "contact_phone": "9876543210",
            "participants": 100, "escorts": 10, **extra,
        }

    def create(self, **extra):
        r = client_for(self.visitor).post(URL, self.payload(**extra), format="json")
        self.assertEqual(r.status_code, 201, r.data)
        return GroupRequest.objects.get(pk=r.data["id"])

    def approve(self, group_request, allocations=None, client=None, **extra):
        if allocations is None:
            allocations = [
                {"slot": self.slots[0].id, "participants": 37, "escorts": 3},
                {"slot": self.slots[1].id, "participants": 33, "escorts": 3},
                {"slot": self.slots[2].id, "participants": 30, "escorts": 4},
            ]
        return (client or client_for(self.staff)).post(
            f"{URL}{group_request.pk}/approve/", {"date": str(self.day), "allocations": allocations, **extra}, format="json"
        )


class CreateValidationTests(GroupRequestBase):
    def post(self, **extra):
        return client_for(self.visitor).post(URL, self.payload(**extra), format="json")

    def test_create(self):
        group_request = self.create()
        self.assertEqual(group_request.status, GroupRequest.Status.SUBMITTED)
        self.assertEqual(group_request.requester, self.visitor)
        self.assertTrue(group_request.reference.startswith("GR-"))

    def test_participants_must_exceed_instant_group_limit(self):
        r = self.post(participants=60, escorts=0)
        self.assertEqual(r.status_code, 400)
        self.assertIn("participants", r.data)
        self.assertEqual(self.post(participants=1001, escorts=0).status_code, 400)

    def test_lead_days_and_window(self):
        soon = timezone.localdate() + datetime.timedelta(days=1)
        r = self.post(preferred_date=str(soon))
        self.assertEqual(r.status_code, 400)
        self.assertIn("days ahead", str(r.data["preferred_date"]))
        r = self.post(preferred_date=str(timezone.localdate() + datetime.timedelta(days=365)))
        self.assertEqual(r.status_code, 400)

    def test_escorts_and_alternative_date(self):
        self.assertIn("escorts", self.post(escorts=11).data)
        self.assertIn("escorts", self.post(group_type="corporate", escorts=1).data)
        self.assertIn("alternative_date", self.post(alternative_date=str(self.day)).data)

    def test_requires_login(self):
        self.assertEqual(client_for().post(URL, self.payload(), format="json").status_code, 401)


class PlanTests(GroupRequestBase):
    def plan(self, group_request, **params):
        r = client_for(self.staff).get(f"{URL}{group_request.pk}/plan/", params)
        self.assertEqual(r.status_code, 200, r.data)
        return r.data

    def test_plan_keeps_20_percent_free_per_slot(self):
        book(make_visitor(), self.museum, self.slots[0], self.day, qty=15, confirm=True)
        group_request = self.create()
        plan = self.plan(group_request)
        self.assertTrue(plan["fits"])
        self.assertEqual(plan["allocated"], 110)
        self.assertEqual(sum(a["participants"] + a["escorts"] for a in plan["allocations"]), 110)
        self.assertEqual(sum(a["escorts"] for a in plan["allocations"]), 10)
        booked = services.booked_visitors_by_slot(self.museum, self.day)
        for alloc in plan["allocations"]:
            slot = next(s for s in self.slots if s.id == alloc["slot_id"])
            free_after = slot.capacity - booked.get(slot.id, 0) - alloc["people"]
            self.assertGreaterEqual(free_after, math.ceil(slot.capacity * 0.2), alloc)
        first = next(s for s in plan["slots"] if s["slot_id"] == self.slots[0].id)
        self.assertEqual((first["free"], first["usable"]), (35, 25))
        group_request.refresh_from_db()
        self.assertIn(group_request.status, GroupRequest.OPEN)

    def test_plan_reports_when_group_does_not_fit(self):
        group_request = self.create(participants=500, escorts=0)
        plan = self.plan(group_request)
        self.assertFalse(plan["fits"])
        self.assertEqual(plan["allocated"], 160)  # every slot offers 40 usable seats (50 minus the 20% reserve)

    def test_preferred_afternoon_falls_back_to_whole_day(self):
        group_request = self.create(preferred_time="afternoon")
        plan = self.plan(group_request)
        self.assertTrue(plan["fits"])
        self.assertIn("whole day", plan["note"])


class ApproveAndPayTests(GroupRequestBase):
    def setUp(self):
        super().setUp()
        self.group_request = self.create()

    def test_approve_creates_pending_bookings_that_hold_seats(self):
        r = self.approve(self.group_request)
        self.assertEqual(r.status_code, 200, r.data)
        self.assertEqual(r.data["status"], "approved")
        bookings = list(self.group_request.bookings.order_by("slot__start_time"))
        self.assertEqual([b.total_visitors for b in bookings], [40, 36, 34])
        self.assertTrue(all(b.status == Booking.Status.PENDING and b.is_group and b.pay_by for b in bookings))
        self.assertEqual(bookings[0].user, self.visitor)
        # school discount 25%: 37 x 50 = 1850 -> 462.50 rounds to 463
        self.assertEqual(bookings[0].discount_amount, 463)
        self.group_request.refresh_from_db()
        self.assertEqual(self.group_request.quoted_total, sum(b.total_amount for b in bookings))
        expected_pay_by = min(timezone.localdate() + datetime.timedelta(days=7), self.day)
        self.assertEqual(timezone.localtime(self.group_request.pay_by).date(), expected_pay_by)

        # seats stay held long after the normal 15-minute hold
        Booking.objects.filter(group_request=self.group_request).update(created_at=timezone.now() - datetime.timedelta(days=2))
        services.expire_stale_bookings()
        self.assertEqual(services.booked_visitors_by_slot(self.museum, self.day)[self.slots[0].id], 40)
        r = client_for(make_visitor()).post("/api/bookings/", booking_payload(self.museum, self.slots[0], self.day, qty=11), format="json")
        self.assertEqual(r.status_code, 400)

    def test_approve_cannot_exceed_slot_capacity(self):
        r = self.approve(self.group_request, allocations=[{"slot": self.slots[0].id, "participants": 51, "escorts": 0}])
        self.assertEqual(r.status_code, 400)
        self.assertFalse(Booking.objects.exists())

    @override_settings(RAZORPAY_KEY_ID="", RAZORPAY_KEY_SECRET="")
    def test_requester_can_pay_online(self):
        self.approve(self.group_request)
        booking = self.group_request.bookings.first()
        r = client_for(self.visitor).post(f"/api/bookings/{booking.reference}/pay/", {"method": "upi"})
        self.assertEqual(r.status_code, 200, r.data)
        self.group_request.refresh_from_db()
        self.assertEqual(self.group_request.status, GroupRequest.Status.APPROVED)  # others still unpaid

    def test_mark_paid_confirms_everything(self):
        self.approve(self.group_request)
        r = client_for(self.staff).post(f"{URL}{self.group_request.pk}/mark-paid/", {"payment_id": "UTR123"}, format="json")
        self.assertEqual(r.status_code, 200, r.data)
        self.assertEqual(r.data["status"], "paid")
        for booking in self.group_request.bookings.all():
            self.assertEqual((booking.status, booking.payment_method, booking.payment_id),
                             (Booking.Status.CONFIRMED, "bank_transfer", "UTR123"))
        r = client_for(self.staff).post(f"{URL}{self.group_request.pk}/decline/", {"reason": "Too late"}, format="json")
        self.assertEqual(r.status_code, 400)

    def test_decline_releases_seats(self):
        self.approve(self.group_request)
        r = client_for(self.staff).post(f"{URL}{self.group_request.pk}/decline/", {"reason": "Event day"}, format="json")
        self.assertEqual(r.status_code, 200, r.data)
        self.assertEqual(r.data["status"], "declined")
        self.assertEqual(r.data["staff_notes"], "Event day")
        self.assertEqual(set(self.group_request.bookings.values_list("status", flat=True)), {Booking.Status.CANCELLED})
        self.assertEqual(services.booked_visitors_by_slot(self.museum, self.day), {})

    def test_lapsed_pay_by_expires_request_and_late_payment_still_accepted(self):
        self.approve(self.group_request)
        Booking.objects.filter(group_request=self.group_request).update(pay_by=timezone.now() - datetime.timedelta(minutes=1))
        services.expire_stale_bookings()
        self.group_request.refresh_from_db()
        self.assertEqual(self.group_request.status, GroupRequest.Status.EXPIRED)
        self.assertEqual(services.booked_visitors_by_slot(self.museum, self.day), {})
        r = client_for(self.staff).post(f"{URL}{self.group_request.pk}/mark-paid/", {}, format="json")
        self.assertEqual(r.status_code, 200, r.data)
        self.assertEqual(r.data["status"], "paid")

    def test_cannot_approve_twice(self):
        self.approve(self.group_request)
        self.assertEqual(self.approve(self.group_request).status_code, 400)


class GroupRequestScopingTests(GroupRequestBase):
    def setUp(self):
        super().setUp()
        self.group_request = self.create()

    def test_visitor_cannot_use_staff_actions(self):
        client = client_for(self.visitor)
        self.assertEqual(client.get(f"{URL}{self.group_request.pk}/plan/").status_code, 403)
        self.assertEqual(self.approve(self.group_request, client=client).status_code, 403)

    def test_visitor_sees_only_own_requests_and_can_cancel(self):
        other = make_visitor()
        self.assertEqual(client_for(other).get(URL).data["count"], 0)
        self.assertEqual(client_for(self.visitor).get(URL).data["count"], 1)
        r = client_for(self.visitor).post(f"{URL}{self.group_request.pk}/cancel/")
        self.assertEqual(r.data["status"], "cancelled")

    def test_staff_of_other_place_cannot_see_or_act(self):
        outsider = make_staff(make_museum())
        self.assertEqual(client_for(outsider).get(URL).data["count"], 0)
        self.assertEqual(client_for(outsider).get(f"{URL}{self.group_request.pk}/plan/").status_code, 404)
        self.assertEqual(self.approve(self.group_request, client=client_for(outsider)).status_code, 404)

    def test_staff_requester_still_needs_assignment_for_staff_actions(self):
        outsider = make_staff(make_museum())
        r = client_for(outsider).post(URL, self.payload(), format="json")
        own = GroupRequest.objects.get(pk=r.data["id"])
        self.assertEqual(client_for(outsider).get(f"{URL}{own.pk}/").status_code, 200)
        self.assertEqual(client_for(outsider).get(f"{URL}{own.pk}/plan/").status_code, 403)


class DateBasedPricingAndClosureTests(GroupRequestBase):
    """Group quotes and approved bookings use the visit date's effective prices; closed dates are refused."""

    def setUp(self):
        super().setUp()
        # a Saturday the place is open, far enough ahead for a group request
        day = timezone.localdate() + datetime.timedelta(days=10)
        while day.weekday() != 5 or self.museum.is_closed_on(day):
            day += datetime.timedelta(days=1)
        self.day = day

    def weekend_rule(self):
        from museums.models import PriceRule

        return PriceRule.objects.create(museum=self.museum, name="Weekend", weekdays="5,6", value=20)

    def quote(self, day, user=None, **extra):
        params = {"museum": self.museum.slug, "date": str(day), "participants": 100, "group_type": "school", **extra}
        return client_for(user or self.visitor).get(f"{URL}quote/", params)

    def test_weekend_price_rule_changes_group_quote(self):
        weekday = self.day - datetime.timedelta(days=2)  # Thursday
        before = self.quote(self.day)
        self.assertEqual(before.status_code, 200, before.data)
        self.assertEqual(before.data["total"], 3750)  # 100 x 50 = 5000, school 25% off
        self.weekend_rule()
        r = self.quote(self.day)
        self.assertEqual((r.data["unit_price"], r.data["price_rule"]), (60, "Weekend"))
        self.assertEqual((r.data["subtotal"], r.data["discount"], r.data["total"]), (6000, 1500, 4500))
        self.assertIsNone(r.data["closed"])
        self.assertEqual(self.quote(weekday).data["total"], 3750)  # weekdays unchanged
        # visitors can't set their own discount; staff can
        self.assertEqual(self.quote(self.day, discount_percent=90).data["discount_percent"], 25)
        self.assertEqual(self.quote(self.day, user=self.staff, discount_percent=10).data["total"], 5400)

    def test_plan_shows_effective_prices(self):
        self.weekend_rule()
        group_request = self.create()
        r = client_for(self.staff).get(f"{URL}{group_request.pk}/plan/")
        self.assertEqual(r.status_code, 200, r.data)
        self.assertEqual(r.data["default_ticket_type"]["price"], 60)
        self.assertEqual(r.data["default_ticket_type"]["base_price"], 50)
        self.assertEqual(r.data["default_ticket_type"]["rule"], "Weekend")

    def test_approved_booking_total_matches_effective_prices(self):
        group_request = self.create()
        self.weekend_rule()
        r = self.approve(group_request)
        self.assertEqual(r.status_code, 200, r.data)
        bookings = list(group_request.bookings.order_by("slot__start_time"))
        for booking in bookings:
            item = booking.items.get()
            self.assertEqual(item.unit_price, 60)
            subtotal = item.unit_price * item.quantity
            self.assertEqual(booking.total_amount + booking.discount_amount, subtotal)
        # 37 x 60 = 2220, 25% = 555
        self.assertEqual((bookings[0].discount_amount, bookings[0].total_amount), (555, 1665))
        group_request.refresh_from_db()
        self.assertEqual(group_request.quoted_total, 100 * 60 * 3 / 4)
        quote = self.quote(self.day).data
        self.assertEqual(group_request.quoted_total, quote["total"])

    def test_holiday_closure_blocks_submit_quote_plan_and_approve(self):
        from museums.models import PlaceClosure

        group_request = self.create()  # submitted before the holiday was added
        PlaceClosure.objects.create(museum=None, start_date=self.day, end_date=self.day, reason="Diwali")
        r = client_for(self.visitor).post(URL, self.payload(), format="json")
        self.assertEqual(r.status_code, 400)
        self.assertIn("Diwali", str(r.data["preferred_date"]))
        self.assertIn("closed", str(r.data["preferred_date"]))
        self.assertIn("Diwali", self.quote(self.day).data["closed"])
        r = client_for(self.staff).get(f"{URL}{group_request.pk}/plan/")
        self.assertEqual(r.status_code, 400)
        self.assertIn("Diwali", str(r.data["date"]))
        r = self.approve(group_request)
        self.assertEqual(r.status_code, 400)
        self.assertIn("Diwali", str(r.data["date"]))
        self.assertFalse(Booking.objects.exists())
        group_request.refresh_from_db()
        self.assertIn(group_request.status, GroupRequest.OPEN)

    def test_staff_moving_the_visit_to_the_weekly_closed_day_is_refused(self):
        from museums.models import Museum

        group_request = self.create()
        Museum.objects.filter(pk=self.museum.pk).update(closed_weekday=self.day.weekday())
        r = self.approve(group_request)
        self.assertEqual(r.status_code, 400)
        self.assertIn("closed", str(r.data["date"]))
        r = client_for(self.visitor).post(URL, self.payload(), format="json")
        self.assertIn("closed", str(r.data["preferred_date"]))

    def test_partial_closure_blocks_that_slot_only(self):
        from museums.models import PlaceClosure

        group_request = self.create()
        closure = PlaceClosure.objects.create(museum=self.museum, start_date=self.day, end_date=self.day,
                                              reason="VIP visit", all_day=False)
        closure.slots.add(self.slots[0])
        r = self.approve(group_request)
        self.assertEqual(r.status_code, 400)
        self.assertIn("VIP visit", str(r.data["allocations"]))
        plan = client_for(self.staff).get(f"{URL}{group_request.pk}/plan/").data
        self.assertEqual(next(s for s in plan["slots"] if s["slot_id"] == self.slots[0].id)["closed_reason"], "VIP visit")
        r = self.approve(group_request, allocations=[
            {"slot": self.slots[1].id, "participants": 34, "escorts": 4},
            {"slot": self.slots[2].id, "participants": 33, "escorts": 3},
            {"slot": self.slots[3].id, "participants": 33, "escorts": 3},
        ])
        self.assertEqual(r.status_code, 200, r.data)

    def test_quote_is_public_and_validated(self):
        r = client_for().get(f"{URL}quote/", {"museum": self.museum.slug, "date": str(self.day), "participants": 80,
                                              "group_type": "tour_operator", "discount_percent": 100})
        self.assertEqual(r.status_code, 200, r.data)
        self.assertEqual((r.data["discount_percent"], r.data["total"]), (10, 3600))  # tour: 10% off 80 x 50
        self.assertFalse(r.data["closed_weekly"])
        self.assertEqual(client_for().get(f"{URL}quote/", {"museum": self.museum.slug}).status_code, 400)
