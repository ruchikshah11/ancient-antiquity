"""Create realistic sample schools and class trips for existing users (idempotent, non-interactive).

    python manage.py seed_schools --users a@x.com,b@y.com [--places slug1,slug2] [--pending 1] [--seed 42]
    call_command("seed_schools", users="a@x.com,b@y.com")                      # from another seeder
    call_command("seed_schools", users=["a@x.com"], places="national-museum-new-delhi")

* One school per user (a user that already has a school keeps it).
* The last --pending users (default 1, and only when two or more users are given) get a school that is
  still waiting for verification; the others get a VERIFIED school with
    - a past class trip: approved, paid and checked in at the gate (one group booking, QR ticket), and
    - an upcoming class trip that is submitted and waiting for staff approval.
* --places: comma-separated slugs (default: up to 6 active places that take groups and sell a student or
  child ticket, featured ones first).
* Re-running creates nothing new for users whose school already has these trips.
"""
import datetime
import random

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.db.models import Q
from django.utils import timezone
from rest_framework.exceptions import ValidationError

from accounts.models import User
from bookings import services as booking_services
from bookings.models import Booking
from museums.models import Museum, State

from schools import services
from schools.models import School, SchoolTrip

SCHOOLS = [
    ("Kendriya Vidyalaya No. 2, Delhi Cantt", "cbse", "New Delhi", "DL", "Delhi Cantonment, New Delhi 110010"),
    ("St. Xavier's High School", "icse", "Mumbai", "MH", "5 Mahapalika Marg, Fort, Mumbai 400001"),
    ("Jawahar Navodaya Vidyalaya, Bolpur", "cbse", "Bolpur", "WB", "Santiniketan Road, Bolpur 731204"),
    ("Government Senior Secondary School, Malviya Nagar", "state", "Jaipur", "RJ", "Sector 6, Malviya Nagar, Jaipur 302017"),
    ("DAV Public School, Gomti Nagar", "cbse", "Lucknow", "UP", "Vipul Khand 2, Gomti Nagar, Lucknow 226010"),
    ("The Hyderabad Public School", "ib", "Hyderabad", "TS", "Begumpet, Hyderabad 500016"),
    ("Sacred Heart Girls' High School", "state", "Bengaluru", "KA", "Richmond Road, Bengaluru 560025"),
    ("Bharatiya Vidya Bhavan's Vidyashram", "cbse", "Chennai", "TN", "KK Nagar, Chennai 600078"),
]
PRINCIPALS = ["Dr. Meena Sharma", "Mr. R. K. Iyer", "Mrs. Farida Khan", "Fr. Thomas D'Souza", "Mrs. Anjali Gupta",
              "Mr. Subhash Chandra", "Sr. Mary Joseph", "Dr. P. Lakshmi"]
GRADES = ["6", "7", "8", "6, 7", "8A, 8B", "5", "9"]
NOTES = ["Students will carry packed lunch.", "Please suggest a two-hour route for the class.",
         "Two students use wheelchairs.", ""]


def _split(value):
    if not value:
        return []
    items = [value] if isinstance(value, str) else list(value)
    return [part.strip() for item in items for part in str(item).split(",") if part.strip()]


class Command(BaseCommand):
    help = "Create realistic sample schools and class trips for the given users (idempotent)."

    def add_arguments(self, parser):
        parser.add_argument("--users", required=True, help="Comma-separated emails of existing users (one school each)")
        parser.add_argument("--places", default="", help="Comma-separated place slugs (default: suitable active places)")
        parser.add_argument("--pending", type=int, default=1, help="How many of the last users get a pending school")
        parser.add_argument("--seed", type=int, default=42, help="Random seed (repeatable data)")

    def handle(self, *args, **opts):
        rng = random.Random(opts["seed"])
        emails = _split(opts["users"])
        if not emails:
            raise CommandError("Give at least one user email with --users.")
        museums = self._places(_split(opts["places"]))
        admin = User.objects.filter(Q(role=User.Role.ADMIN) | Q(is_superuser=True)).order_by("id").first()
        pending = min(max(opts["pending"], 0), len(emails) - 1) if len(emails) > 1 else 0
        counts = {"schools": 0, "past": 0, "upcoming": 0}
        for k, email in enumerate(emails):
            user = User.objects.filter(email__iexact=email).first()
            if user is None:
                raise CommandError(f"No user with email {email}")
            verified = k < len(emails) - pending
            school = School.objects.filter(owner=user).first()
            if school is None:
                school = self._make_school(user, k, verified, admin, rng)
                counts["schools"] += 1
            if not school.is_verified:
                continue
            museum = museums[k % len(museums)]
            today = timezone.localdate()
            if not school.trips.filter(approved_date__lt=today).exists():
                if self._past_trip(school, user, museum, admin, rng):
                    counts["past"] += 1
            upcoming = museums[(k + 1) % len(museums)]
            if not school.trips.filter(status=SchoolTrip.Status.SUBMITTED, preferred_date__gt=today).exists():
                if self._upcoming_trip(school, user, upcoming, rng):
                    counts["upcoming"] += 1
        self.stdout.write(self.style.SUCCESS(
            f"Schools created: {counts['schools']}, past paid trips: {counts['past']}, "
            f"upcoming requests: {counts['upcoming']}"
        ))

    # ---------------------------------------------------------------------------------------------

    def _places(self, slugs):
        qs = Museum.objects.filter(is_active=True, allow_groups=True, slots__is_active=True).distinct()
        if slugs:
            found = list(qs.filter(slug__in=slugs))
            missing = set(slugs) - {m.slug for m in found}
            if missing:
                raise CommandError(f"Unknown, inactive or group-less places: {', '.join(sorted(missing))}")
            return found
        found = list(
            qs.filter(Q(ticket_types__name__icontains="student") | Q(ticket_types__name__icontains="child"),
                      ticket_types__is_active=True).distinct().order_by("-is_featured", "name")[:6]
        ) or list(qs.order_by("-is_featured", "name")[:6])
        if not found:
            raise CommandError("No active places with time slots that take groups. Seed places first.")
        return found

    def _make_school(self, user, k, verified, admin, rng):
        name, board, city, code, address = SCHOOLS[k % len(SCHOOLS)]
        state = State.objects.filter(code=code).first() or State.objects.order_by("name").first()
        if state is None:
            raise CommandError("No states in the database. Seed places first.")
        now = timezone.now()
        return School.objects.create(
            owner=user, name=name, board=board, udise_code="".join(rng.choice("0123456789") for _ in range(11)),
            address=address, city=city, state=state, principal_name=PRINCIPALS[k % len(PRINCIPALS)],
            phone=f"0{rng.randint(11, 99)}{rng.randint(20000000, 29999999)}",
            contact_name=f"{user.first_name} {user.last_name}".strip() or user.email.split("@")[0].title(),
            contact_phone=user.phone or f"9{rng.randint(100000000, 999999999)}", contact_email=user.email,
            status=School.Status.VERIFIED if verified else School.Status.PENDING,
            verified_by=admin if verified else None, verified_at=now if verified else None,
        )

    def _class(self, rng):
        students = rng.choice([24, 32, 36, 40, 45])
        return students, services.teachers_needed(students) + rng.choice([0, 1]), rng.choice([0, 1, 2])

    def _past_trip(self, school, user, museum, admin, rng):
        """Approved, paid and checked-in visit 2-6 weeks ago (built with the booking service directly,
        because approval only accepts future dates)."""
        today = timezone.localdate()
        day = today - datetime.timedelta(days=rng.randint(14, 42))
        for _ in range(14):
            if not museum.is_closed_on(day) and not museum.closure_on(day)["closed"]:
                break
            day -= datetime.timedelta(days=1)
        students, teachers, helpers = self._class(rng)
        trip = SchoolTrip(
            school=school, requested_by=user, museum=museum, preferred_date=day, slot_preference="morning",
            grades=rng.choice(GRADES), students=students, teachers=teachers, helpers=helpers,
            guide_language=rng.choice(["hi", "en"]), notes=rng.choice(NOTES),
        )
        est = services.estimate_for_trip(trip, day)
        items = [{"ticket_type": line["ticket_type"], "quantity": line["quantity"]} for line in est["lines"]]
        with transaction.atomic():
            booking = None
            for slot in services.candidate_slots(museum, day, "morning"):
                try:
                    with transaction.atomic():
                        booking = booking_services.create_booking(
                            user=user, museum=museum, slot=slot, visit_date=day, items=items,
                            visitor_name=school.contact_name, visitor_email=school.contact_email,
                            visitor_phone=school.contact_phone, group_type=Booking.GroupType.SCHOOL,
                            organisation_name=school.name[:150], escort_count=est["free_teachers"],
                        )
                    break
                except ValidationError:  # slot full or closed: try the next one
                    continue
            if booking is None:
                self.stdout.write(self.style.WARNING(f"{museum.name}: no room on {day} for a past trip, skipped"))
                return False
            if booking.status == Booking.Status.PENDING:
                booking_services.confirm_payment(booking, Booking.PaymentMethod.UPI)
            at = timezone.make_aware(datetime.datetime.combine(day, booking.slot.start_time)) + datetime.timedelta(minutes=10)
            booking_services.mark_checked_in(booking, admin or user, at=at)
            decided = at - datetime.timedelta(days=10)
            trip.status = SchoolTrip.Status.APPROVED
            trip.estimated_amount = est["total"]
            trip.quoted_amount = booking.total_amount
            trip.approved_date = day
            trip.booking = booking
            trip.decided_by = admin
            trip.decided_at = decided
            trip.staff_note = "Please arrive 15 minutes before your slot; the guide will meet you at the ticket office."
            trip.save()
            SchoolTrip.objects.filter(pk=trip.pk).update(created_at=decided - datetime.timedelta(days=3))
            Booking.objects.filter(pk=booking.pk).update(created_at=decided, paid_at=decided + datetime.timedelta(days=1))
        return True

    def _upcoming_trip(self, school, user, museum, rng):
        day = timezone.localdate() + datetime.timedelta(days=rng.randint(12, 40))
        for _ in range(14):
            if services.visit_day_error(museum, day) is None:
                break
            day += datetime.timedelta(days=1)
        else:
            return False
        alt = day + datetime.timedelta(days=7)
        if services.visit_day_error(museum, alt):
            alt = None
        students, teachers, helpers = self._class(rng)
        est = services.estimate(museum, day, students, teachers, helpers)
        SchoolTrip.objects.create(
            school=school, requested_by=user, museum=museum, preferred_date=day, alternative_date=alt,
            slot_preference=rng.choice(SchoolTrip.SlotPreference.values), grades=rng.choice(GRADES),
            students=students, teachers=teachers, helpers=helpers, guide_language=rng.choice(["", "hi", "en"]),
            accessibility_needs=rng.choice(["", "", "One student uses a wheelchair."]), notes=rng.choice(NOTES),
            estimated_amount=est["total"],
        )
        return True
