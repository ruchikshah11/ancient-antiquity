import datetime
import io
from decimal import Decimal

from django.core import mail
from django.core.management import call_command
from django.utils import timezone

from bookings.models import Booking
from bookings.tests.factories import (
    APITestCase,
    client_for,
    future_open_date,
    make_admin,
    make_museum,
    make_staff,
    make_state,
    make_visitor,
)
from museums.models import PlaceClosure

from . import services
from .models import School, SchoolTrip

TICKETS = (
    ("Indian Citizen (Adult)", "50.00"),
    ("Foreign National", "600.00"),
    ("Student", "20.00"),
    ("Child (below 15)", "0.00"),
)
SLOTS = ((datetime.time(10, 0), datetime.time(12, 0), 200), (datetime.time(14, 0), datetime.time(16, 0), 200))
MINE = "/api/schools/mine/"
TRIPS = "/api/schools/trips/"
ESTIMATE = "/api/schools/estimate/"


def make_school(owner=None, status=School.Status.VERIFIED, **kw):
    owner = owner or make_visitor()
    return School.objects.create(
        owner=owner, name=kw.pop("name", "Kendriya Vidyalaya No. 1"), board=School.Board.CBSE, address="Sector 4",
        city="New Delhi", state=kw.pop("state", None) or make_state(), principal_name="Dr. Meena Sharma",
        phone="9876543210", contact_name="Asha Rao", contact_phone="9876543211",
        contact_email=kw.pop("contact_email", "asha@school.example"), status=status, **kw,
    )


def trip_payload(museum, day=None, **extra):
    return {
        "museum": museum.slug,
        "preferred_date": str(day or future_open_date(museum)),
        "slot_preference": "morning",
        "grades": "6, 7",
        "students": 40,
        "teachers": 3,
        "helpers": 1,
        "guide_language": "hi",
        "notes": "Packed lunch",
        **extra,
    }


def make_trip(school, museum, day=None, **kw):
    day = day or future_open_date(museum)
    fields = dict(students=40, teachers=3, helpers=1, grades="6", slot_preference="morning")
    fields.update(kw)
    return SchoolTrip.objects.create(school=school, requested_by=school.owner, museum=museum, preferred_date=day,
                                     **fields)


def weekday_ahead(weekday, min_days=5):
    day = timezone.localdate() + datetime.timedelta(days=min_days)
    while day.weekday() != weekday:
        day += datetime.timedelta(days=1)
    return day


class SchoolRegistrationTests(APITestCase):
    def setUp(self):
        super().setUp()
        self.state = make_state()
        self.teacher = make_visitor(first_name="Asha", last_name="Rao", phone="9876543210")
        self.client = client_for(self.teacher)

    def payload(self, **extra):
        return {"name": "DAV Public School", "board": "cbse", "udise_code": "", "address": "1 Mall Road",
                "city": "Pune", "state": self.state.id, "principal_name": "Mr. Iyer", "phone": "02012345678", **extra}

    def test_no_school_is_404(self):
        self.assertEqual(self.client.get(MINE).status_code, 404)

    def test_register_defaults_contact_to_user_and_is_pending(self):
        r = self.client.post(MINE, self.payload(), format="json")
        self.assertEqual(r.status_code, 201, r.data)
        self.assertEqual(r.data["status"], "pending")
        self.assertEqual(r.data["contact_email"], self.teacher.email)
        self.assertEqual(r.data["contact_name"], "Asha Rao")
        self.assertEqual(r.data["contact_phone"], "9876543210")
        self.assertEqual(self.client.get(MINE).data["name"], "DAV Public School")

    def test_udise_must_be_11_digits(self):
        r = self.client.post(MINE, self.payload(udise_code="12345"), format="json")
        self.assertEqual(r.status_code, 400)
        self.assertIn("udise_code", r.data)
        r = self.client.post(MINE, self.payload(udise_code="27251234567"), format="json")
        self.assertEqual(r.status_code, 201, r.data)

    def test_one_school_per_user(self):
        self.client.post(MINE, self.payload(), format="json")
        r = self.client.post(MINE, self.payload(name="Second"), format="json")
        self.assertEqual(r.status_code, 400)
        self.assertEqual(School.objects.filter(owner=self.teacher).count(), 1)

    def test_status_cannot_be_set_by_teacher(self):
        r = self.client.post(MINE, self.payload(status="verified"), format="json")
        self.assertEqual(r.data["status"], "pending")

    def test_editing_rejected_school_resubmits_it(self):
        make_school(self.teacher, status=School.Status.REJECTED, rejection_reason="Wrong UDISE")
        r = self.client.patch(MINE, {"udise_code": "27251234567"}, format="json")
        self.assertEqual(r.status_code, 200, r.data)
        self.assertEqual(r.data["status"], "pending")
        self.assertEqual(r.data["rejection_reason"], "")

    def test_verified_school_can_only_change_contacts(self):
        make_school(self.teacher)
        self.assertEqual(self.client.patch(MINE, {"name": "Other"}, format="json").status_code, 400)
        r = self.client.patch(MINE, {"contact_name": "New Teacher"}, format="json")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.data["status"], "verified")

    def test_admin_verifies_and_rejects_with_email(self):
        school = make_school(self.teacher, status=School.Status.PENDING)
        admin = client_for(make_admin())
        with self.captureOnCommitCallbacks(execute=True):
            r = admin.post(f"/api/schools/{school.id}/verify/")
        self.assertEqual(r.status_code, 200, r.data)
        school.refresh_from_db()
        self.assertEqual(school.status, "verified")
        self.assertIsNotNone(school.verified_at)
        self.assertIn("verified", mail.outbox[-1].subject)
        self.assertEqual(admin.post(f"/api/schools/{school.id}/reject/").status_code, 400)  # reason required
        with self.captureOnCommitCallbacks(execute=True):
            r = admin.post(f"/api/schools/{school.id}/reject/", {"reason": "Not a school"})
        self.assertEqual(r.data["status"], "rejected")
        self.assertIn("Not a school", mail.outbox[-1].body)

    def test_school_list_is_admin_only(self):
        make_school()
        self.assertEqual(client_for(make_staff()).get("/api/schools/").status_code, 403)
        self.assertEqual(self.client.get("/api/schools/").status_code, 403)
        r = client_for(make_admin()).get("/api/schools/", {"status": "verified"})
        self.assertEqual(r.data["count"], 1)
        self.assertEqual(r.data["results"][0]["trip_count"], 0)


class EstimateTests(APITestCase):
    def setUp(self):
        super().setUp()
        self.museum = make_museum(tickets=TICKETS, slots=SLOTS, school_discount_percent=25)
        self.day = future_open_date(self.museum)

    def test_students_student_price_teachers_free_per_20_helpers_adult(self):
        est = services.estimate(self.museum, self.day, students=40, teachers=3, helpers=1)
        # 40 x 20 (student) + (3 teachers - 2 free + 1 helper) x 50 = 900; 25% school discount = 225
        self.assertEqual(est["free_teachers"], 2)
        self.assertEqual(est["subtotal"], Decimal("900"))
        self.assertEqual(est["discount"], Decimal("225"))
        self.assertEqual(est["total"], Decimal("675"))
        self.assertEqual(est["people"], 44)

    def test_young_students_use_child_ticket(self):
        est = services.estimate(self.museum, self.day, students=40, teachers=2, helpers=0, young_students=30)
        # 10 x 20 + 30 x 0 + 0 adults
        self.assertEqual(est["subtotal"], Decimal("200"))
        self.assertEqual([(l["name"], l["quantity"]) for l in est["lines"]],
                         [("Student", 10), ("Child (below 15)", 30)])

    def test_free_teachers_rounds_up_and_never_exceeds_teachers(self):
        self.assertEqual(services.free_teachers(21, 5), 2)
        self.assertEqual(services.free_teachers(40, 1), 1)
        self.assertEqual(services.teachers_needed(20), 1)
        self.assertEqual(services.teachers_needed(41), 3)

    def test_without_student_ticket_falls_back_to_child_then_adult(self):
        asi = make_museum(tickets=(("Indian Citizen (Adult)", "40.00"), ("Foreign National", "600.00"),
                                   ("Child (below 15)", "0.00")), school_discount_percent=0)
        est = services.estimate(asi, self.day, students=30, teachers=2, helpers=0)
        self.assertEqual(est["total"], Decimal("0"))  # ASI: children free, 2 teachers free for 30 students
        plain = make_museum(tickets=(("Indian adult", "50.00"),), school_discount_percent=0)
        est = services.estimate(plain, self.day, students=30, teachers=3, helpers=0)
        self.assertEqual(len(est["lines"]), 1)  # students and the paying teacher share the adult ticket
        self.assertEqual(est["lines"][0]["quantity"], 31)
        self.assertEqual(est["total"], Decimal("1550"))

    def test_estimate_endpoint(self):
        r = client_for(make_visitor()).post(ESTIMATE, {"museum": self.museum.slug, "date": str(self.day),
                                                      "students": 40, "teachers": 3, "helpers": 1}, format="json")
        self.assertEqual(r.status_code, 200, r.data)
        self.assertEqual(r.data["total"], "675.00")
        self.assertEqual(r.data["student_ticket"]["name"], "Student")
        self.assertEqual(r.data["child_ticket"]["name"], "Child (below 15)")
        self.assertIsNone(r.data["date_error"])

    def test_estimate_needs_login(self):
        self.assertEqual(client_for().post(ESTIMATE, {}, format="json").status_code, 401)


class TripRequestTests(APITestCase):
    def setUp(self):
        super().setUp()
        self.museum = make_museum(tickets=TICKETS, slots=SLOTS, closed_weekday=0)
        self.school = make_school()
        self.client = client_for(self.school.owner)

    def post(self, **extra):
        return self.client.post(TRIPS, trip_payload(self.museum, **extra), format="json")

    def test_verified_school_submits_with_estimate(self):
        r = self.post()
        self.assertEqual(r.status_code, 201, r.data)
        self.assertEqual(r.data["status"], "submitted")
        self.assertEqual(r.data["estimated_amount"], "675.00")
        self.assertEqual(r.data["free_teachers"], 2)
        self.assertTrue(r.data["can_cancel"])
        self.assertEqual(self.client.get(TRIPS).data["count"], 1)

    def test_verification_required(self):
        self.school.status = School.Status.PENDING
        self.school.save()
        r = self.post()
        self.assertEqual(r.status_code, 403)
        self.assertIn("waiting for verification", str(r.data))

    def test_no_school_cannot_request(self):
        self.assertEqual(client_for(make_visitor()).post(TRIPS, trip_payload(self.museum), format="json").status_code, 403)

    def test_closed_weekday_rejected(self):
        r = self.post(preferred_date=str(weekday_ahead(0)))
        self.assertEqual(r.status_code, 400)
        self.assertIn("preferred_date", r.data)

    def test_whole_day_closure_rejected_partial_allowed(self):
        day = future_open_date(self.museum, 12)
        PlaceClosure.objects.create(museum=None, start_date=day, end_date=day, reason="Republic Day")
        r = self.post(preferred_date=str(day))
        self.assertEqual(r.status_code, 400)
        self.assertIn("Republic Day", str(r.data))
        other = future_open_date(self.museum, 20)
        partial = PlaceClosure.objects.create(museum=self.museum, start_date=other, end_date=other, reason="VIP", all_day=False)
        partial.slots.add(self.museum.slots.first())
        self.assertEqual(self.post(preferred_date=str(other)).status_code, 201)

    def test_past_today_and_beyond_window_rejected(self):
        today = timezone.localdate()
        for day in (today - datetime.timedelta(days=1), today, today + datetime.timedelta(days=200)):
            r = self.post(preferred_date=str(day))
            self.assertEqual(r.status_code, 400, day)
            self.assertIn("preferred_date", r.data)

    def test_alternative_date_checked(self):
        day = future_open_date(self.museum)
        self.assertEqual(self.post(preferred_date=str(day), alternative_date=str(day)).status_code, 400)
        r = self.post(preferred_date=str(day), alternative_date=str(weekday_ahead(0)))
        self.assertIn("alternative_date", r.data)

    def test_teacher_ratio(self):
        r = self.post(students=41, teachers=2)
        self.assertEqual(r.status_code, 400)
        self.assertIn("3 teacher(s)", str(r.data["teachers"]))
        self.assertEqual(self.post(students=41, teachers=3).status_code, 201)

    def test_minimum_students(self):
        r = self.post(students=9, teachers=1)
        self.assertEqual(r.status_code, 400)
        self.assertIn("students", r.data)

    def test_young_students_cannot_exceed_students(self):
        self.assertEqual(self.post(students=20, young_students=21, teachers=1).status_code, 400)

    def test_place_without_groups(self):
        self.museum.allow_groups = False
        self.museum.save()
        self.assertEqual(self.post().status_code, 400)

    def test_teacher_cancels_only_before_approval(self):
        trip = make_trip(self.school, self.museum)
        other = client_for(make_visitor())
        self.assertEqual(other.post(f"{TRIPS}{trip.id}/cancel/").status_code, 404)
        r = self.client.post(f"{TRIPS}{trip.id}/cancel/")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.data["status"], "cancelled")
        trip2 = make_trip(self.school, self.museum)
        services.approve_trip(trip2, by_user=None, visit_date=trip2.preferred_date)
        self.assertEqual(self.client.post(f"{TRIPS}{trip2.id}/cancel/").status_code, 400)


class StaffFlowTests(APITestCase):
    def setUp(self):
        super().setUp()
        self.museum = make_museum(tickets=TICKETS, slots=SLOTS, school_discount_percent=25)
        self.other = make_museum(tickets=TICKETS, slots=SLOTS)
        self.school = make_school()
        self.teacher = client_for(self.school.owner)
        self.staff_user = make_staff(self.museum)
        self.staff = client_for(self.staff_user)
        self.trip = make_trip(self.school, self.museum)
        self.other_trip = make_trip(self.school, self.other)

    def approve(self, client=None, trip=None, **body):
        trip = trip or self.trip
        with self.captureOnCommitCallbacks(execute=True):
            return (client or self.staff).post(f"{TRIPS}{trip.id}/approve/", body, format="json")

    def test_staff_sees_only_assigned_places_admin_all(self):
        ids = [t["id"] for t in self.staff.get(TRIPS).data["results"]]
        self.assertEqual(ids, [self.trip.id])
        self.assertEqual(client_for(make_admin()).get(TRIPS).data["count"], 2)
        self.assertEqual(self.staff.get(TRIPS, {"museum": self.other.slug}).data["count"], 0)
        self.assertEqual(self.staff.post(f"{TRIPS}{self.other_trip.id}/approve/").status_code, 404)
        self.assertEqual(self.teacher.post(f"{TRIPS}{self.trip.id}/approve/").status_code, 403)

    def test_filters(self):
        admin = client_for(make_admin())
        self.assertEqual(admin.get(TRIPS, {"status": "approved"}).data["count"], 0)
        self.assertEqual(admin.get(TRIPS, {"date": str(self.trip.preferred_date)}).data["count"], 2)

    def test_approve_creates_payable_group_booking_with_estimate_amount(self):
        r = self.approve(staff_note="Please arrive 15 minutes early.")
        self.assertEqual(r.status_code, 200, r.data)
        self.assertEqual(r.data["status"], "approved")
        self.assertEqual(r.data["quoted_amount"], "675.00")
        self.assertTrue(r.data["can_pay"])
        booking = Booking.objects.get(reference=r.data["booking"]["reference"])
        self.assertEqual(booking.status, Booking.Status.PENDING)
        self.assertTrue(booking.is_group)
        self.assertEqual(booking.group_type, "school")
        self.assertEqual(booking.user, self.school.owner)
        self.assertEqual(booking.total_visitors, 44)
        self.assertEqual(booking.escort_count, 2)
        self.assertEqual(booking.total_amount, Decimal("675"))
        self.assertEqual(booking.slot.start_time, datetime.time(10, 0))  # morning preference
        self.assertIsNotNone(booking.pay_by)
        # seats stay held after the normal 15-minute hold
        Booking.objects.filter(pk=booking.pk).update(created_at=timezone.now() - datetime.timedelta(hours=2))
        r = self.teacher.post(f"/api/bookings/{booking.reference}/pay/", {"method": "upi"}, format="json")
        self.assertEqual(r.status_code, 200, r.data)
        booking.refresh_from_db()
        self.assertEqual(booking.status, Booking.Status.CONFIRMED)
        r = self.teacher.get(f"{TRIPS}{self.trip.id}/")
        self.assertFalse(r.data["can_pay"])
        self.assertEqual(r.data["booking"]["status"], "confirmed")
        # emails: approval with pay link
        approved = [m for m in mail.outbox if "approved" in m.subject]
        self.assertEqual(len(approved), 1)
        self.assertEqual(approved[0].to, ["asha@school.example"])
        self.assertIn(f"/checkout/{booking.reference}", approved[0].body)
        self.assertIn("arrive 15 minutes early", approved[0].body)
        # mark completed once paid
        r = self.staff.post(f"{TRIPS}{self.trip.id}/complete/")
        self.assertEqual(r.status_code, 200, r.data)
        self.assertEqual(r.data["status"], "completed")

    def test_complete_requires_payment(self):
        self.approve()
        self.assertEqual(self.staff.post(f"{TRIPS}{self.trip.id}/complete/").status_code, 400)

    def test_quote_override_sets_booking_total(self):
        r = self.approve(quoted_amount="500.00")
        self.assertEqual(r.status_code, 200, r.data)
        booking = Booking.objects.get(pk=SchoolTrip.objects.get(pk=self.trip.pk).booking_id)
        self.assertEqual(booking.total_amount, Decimal("500"))
        self.assertEqual(booking.discount_amount, Decimal("400"))  # gross 900
        self.assertEqual(booking.tickets_amount, Decimal("900"))
        self.assertEqual(r.data["quoted_amount"], "500.00")

    def test_quote_above_ticket_total_rejected(self):
        r = self.approve(quoted_amount="901")
        self.assertEqual(r.status_code, 400)
        self.assertFalse(Booking.objects.exists())
        self.trip.refresh_from_db()
        self.assertEqual(self.trip.status, "submitted")

    def test_zero_quote_confirms_free(self):
        r = self.approve(quoted_amount="0")
        self.assertEqual(r.data["booking"]["status"], "confirmed")
        self.assertFalse(r.data["can_pay"])

    def test_free_class_is_confirmed_at_once(self):
        asi = make_museum(tickets=(("Indian Citizen (Adult)", "40.00"), ("Child (below 15)", "0.00")), slots=SLOTS)
        asi.staff.add(self.staff_user)
        trip = make_trip(self.school, asi, students=30, teachers=2, helpers=0)
        r = self.approve(trip=trip)
        self.assertEqual(r.status_code, 200, r.data)
        self.assertEqual(r.data["booking"]["status"], "confirmed")
        self.assertEqual(r.data["quoted_amount"], "0.00")

    def test_alternative_date_and_afternoon_slot(self):
        alt = future_open_date(self.museum, 20)
        self.trip.alternative_date = alt
        self.trip.slot_preference = "afternoon"
        self.trip.save()
        self.assertEqual(self.approve(date=str(alt + datetime.timedelta(days=1))).status_code, 400)
        r = self.approve(date=str(alt))
        self.assertEqual(r.status_code, 200, r.data)
        self.assertEqual(r.data["approved_date"], str(alt))
        self.assertEqual(r.data["booking"]["visit_date"], str(alt))
        self.assertEqual(Booking.objects.get().slot.start_time, datetime.time(14, 0))

    def test_group_share_respected_and_falls_back_to_other_slot(self):
        small = make_museum(tickets=TICKETS, slots=(
            (datetime.time(10, 0), datetime.time(12, 0), 100),   # group share 30: the class of 44 does not fit
            (datetime.time(14, 0), datetime.time(16, 0), 200),   # group share 60
        ))
        small.staff.add(self.staff_user)
        trip = make_trip(self.school, small)
        slot_ids = [s["slot_id"] for s in self.staff.get(f"{TRIPS}{trip.id}/slots/").data["slots"]]
        self.assertEqual(len(slot_ids), 2)
        r = self.approve(trip=trip, slot=slot_ids[0])
        self.assertEqual(r.status_code, 400)
        self.assertIn("No slot", str(r.data))
        r = self.approve(trip=trip)
        self.assertEqual(r.status_code, 200, r.data)
        self.assertEqual(Booking.objects.get(school_trips=trip).slot_id, slot_ids[1])

    def test_no_room_gives_clear_error(self):
        tiny = make_museum(tickets=TICKETS, slots=((datetime.time(10, 0), datetime.time(12, 0), 50),))
        tiny.staff.add(self.staff_user)
        trip = make_trip(self.school, tiny)
        r = self.approve(trip=trip)
        self.assertEqual(r.status_code, 400)
        self.assertIn("has room for this class of 44", str(r.data))
        trip.refresh_from_db()
        self.assertEqual(trip.status, "submitted")

    def test_approve_rechecks_closure(self):
        PlaceClosure.objects.create(museum=self.museum, start_date=self.trip.preferred_date,
                                    end_date=self.trip.preferred_date, reason="Flooding")
        r = self.approve()
        self.assertEqual(r.status_code, 400)
        self.assertIn("Flooding", str(r.data))

    def test_cannot_approve_twice(self):
        self.approve()
        self.assertEqual(self.approve().status_code, 400)
        self.assertEqual(Booking.objects.count(), 1)

    def test_decline_submitted_sends_reason(self):
        self.assertEqual(self.staff.post(f"{TRIPS}{self.trip.id}/decline/", {}).status_code, 400)
        with self.captureOnCommitCallbacks(execute=True):
            r = self.staff.post(f"{TRIPS}{self.trip.id}/decline/", {"reason": "Gallery closed for renovation"})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.data["status"], "declined")
        self.assertEqual(mail.outbox[-1].to, ["asha@school.example"])
        self.assertIn("declined", mail.outbox[-1].subject)
        self.assertIn("Gallery closed for renovation", mail.outbox[-1].body)

    def test_decline_approved_releases_unpaid_booking(self):
        self.approve()
        r = self.staff.post(f"{TRIPS}{self.trip.id}/decline/", {"reason": "Event day"})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(Booking.objects.get().status, Booking.Status.CANCELLED)

    def test_cannot_decline_paid_trip(self):
        self.approve()
        booking = Booking.objects.get()
        self.teacher.post(f"/api/bookings/{booking.reference}/pay/", {"method": "upi"}, format="json")
        self.assertEqual(self.staff.post(f"{TRIPS}{self.trip.id}/decline/", {"reason": "x"}).status_code, 400)

    def test_teacher_sees_own_trips_only_with_mine(self):
        self.assertEqual(self.teacher.get(TRIPS).data["count"], 2)
        self.assertEqual(client_for(make_visitor()).get(TRIPS).data["count"], 0)
        self.assertEqual(self.staff.get(TRIPS, {"mine": 1}).data["count"], 0)

    def test_trip_estimate_endpoint(self):
        r = self.teacher.get(f"{TRIPS}{self.trip.id}/estimate/")
        self.assertEqual(r.data["total"], "675.00")


class SeedCommandTests(APITestCase):
    def test_seed_creates_realistic_data_and_is_idempotent(self):
        museum = make_museum(tickets=TICKETS, slots=SLOTS)
        make_museum(tickets=(("Indian adult", "50.00"),), slots=SLOTS)  # no student/child ticket: not a default
        make_admin()
        users = [make_visitor(), make_visitor(), make_visitor()]
        emails = ",".join(u.email for u in users)
        call_command("seed_schools", users=emails, stdout=io.StringIO())
        call_command("seed_schools", "--users", emails, stdout=io.StringIO())
        self.assertEqual(School.objects.count(), 3)
        self.assertEqual(School.objects.filter(status="pending").count(), 1)
        self.assertEqual(School.objects.get(owner=users[2]).status, "pending")
        today = timezone.localdate()
        past = SchoolTrip.objects.filter(approved_date__lt=today)
        self.assertEqual(past.count(), 2)
        for trip in past:
            self.assertEqual(trip.museum, museum)
            self.assertEqual(trip.status, "approved")
            self.assertTrue(services.is_paid(trip))
            self.assertEqual(trip.booking.total_amount, trip.quoted_amount)
        upcoming = SchoolTrip.objects.filter(status="submitted")
        self.assertEqual(upcoming.count(), 2)
        self.assertTrue(all(t.preferred_date > today for t in upcoming))
        self.assertEqual(SchoolTrip.objects.count(), 4)

    def test_seed_with_places_and_list_users(self):
        museum = make_museum(tickets=TICKETS, slots=SLOTS)
        user = make_visitor()
        call_command("seed_schools", users=[user.email], places=museum.slug, stdout=io.StringIO())
        self.assertEqual(School.objects.get().status, "verified")  # a single user is never left pending
        self.assertEqual(SchoolTrip.objects.count(), 2)
