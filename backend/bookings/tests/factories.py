"""Shared test helpers: places, users, API clients and bookings.

Used by the tests of every app (``from bookings.tests.factories import ...``). Nothing here touches the
real database: Django's test runner creates a throwaway test database for the run.

Dates are always relative to ``timezone.localdate()`` so the suite works on any day. Tests that depend on
the time of day patch ``django.utils.timezone.now`` with :func:`frozen_now`.
"""
import datetime
import itertools
import logging
from contextlib import contextmanager
from decimal import Decimal
from unittest import mock

from django.core.cache import cache
from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from accounts.models import User
from bookings import services
from bookings.models import Booking
from museums.models import Category, City, Museum, State, TicketType, TimeSlot

# Expected 4xx responses are logged as warnings by Django; keep the test output readable.
logging.getLogger("django.request").setLevel(logging.ERROR)
logging.getLogger("notifications.services").setLevel(logging.CRITICAL)  # SMS console + deliberate send failures

_seq = itertools.count(1)

ALL_DAY = (datetime.time(0, 0), datetime.time(23, 59, 59))
PHONE = "9876543210"


def _n():
    return next(_seq)


# ------------------------------------------------------------------ places

def make_state(name=None, code=None):
    n = _n()
    return State.objects.create(name=name or f"State {n}", code=code or f"S{n}"[-4:])  # last 4: unique for n < 10000


def make_city(state=None, name=None):
    return City.objects.create(name=name or f"City {_n()}", state=state or make_state())


def make_category(name=None):
    return Category.objects.create(name=name or f"Category {_n()}")


def make_museum(
    name=None, *, city=None, state=None, category=None, place_type=Museum.PlaceType.MUSEUM,
    slots=((datetime.time(10, 0), datetime.time(11, 0), 100), (datetime.time(14, 0), datetime.time(15, 0), 100)),
    tickets=(("Indian adult", "50.00"), ("Foreign national", "600.00")),
    closed_weekday=None, **extra,
):
    """A place with ticket types and daily slots. ``slots`` is a list of (start, end, capacity)."""
    if city is None:
        city = make_city(state=state)
    museum = Museum.objects.create(
        name=name or f"Museum {_n()}",
        city=city,
        category=category,
        place_type=place_type,
        description="A test place.",
        address="1 Test Road",
        opening_time=datetime.time(0, 0),
        closing_time=datetime.time(23, 59, 59),
        closed_weekday=closed_weekday,
        **extra,
    )
    for order, (ticket_name, price) in enumerate(tickets):
        TicketType.objects.create(museum=museum, name=ticket_name, price=Decimal(price), sort_order=order)
    for start, end, capacity in slots:
        TimeSlot.objects.create(museum=museum, start_time=start, end_time=end, capacity=capacity)
    return museum


def add_slot(museum, start=ALL_DAY[0], end=ALL_DAY[1], capacity=200):
    return TimeSlot.objects.create(museum=museum, start_time=start, end_time=end, capacity=capacity)


def ticket(museum, name="Indian adult"):
    return museum.ticket_types.get(name=name)


def first_slot(museum):
    return museum.slots.order_by("start_time").first()


def future_open_date(museum=None, days_ahead=10):
    """First day at least ``days_ahead`` days from today on which ``museum`` is open."""
    day = timezone.localdate() + datetime.timedelta(days=days_ahead)
    while museum is not None and museum.is_closed_on(day):
        day += datetime.timedelta(days=1)
    return day


def at(day, hour, minute=0):
    """Aware datetime in the project time zone (Asia/Kolkata)."""
    return timezone.make_aware(datetime.datetime.combine(day, datetime.time(hour, minute)))


@contextmanager
def frozen_now(moment):
    """Pretend the current time is ``moment`` (affects timezone.now/localdate/localtime and auto_now fields)."""
    with mock.patch("django.utils.timezone.now", return_value=moment):
        yield moment


# ------------------------------------------------------------------ users and clients

def make_user(role=User.Role.VISITOR, email=None, password=None, **extra):
    """Users get an unusable password unless one is given (Argon2 hashing is deliberately slow)."""
    email = email or f"{role}{_n()}@example.com"
    return User.objects.create_user(email=email, password=password, role=role, **extra)


def make_visitor(**kw):
    return make_user(User.Role.VISITOR, **kw)


def make_staff(*museums, **kw):
    user = make_user(User.Role.STAFF, **kw)
    for museum in museums:
        museum.staff.add(user)
    return user


def make_admin(**kw):
    return make_user(User.Role.ADMIN, **kw)


def client_for(user=None):
    client = APIClient()
    if user is not None:
        client.force_authenticate(user)
    return client


# ------------------------------------------------------------------ bookings

def book(user, museum, slot=None, visit_date=None, qty=1, ticket_name="Indian adult", *, confirm=False,
         method=Booking.PaymentMethod.UPI, **kw):
    """Create a booking straight through the service layer (skips the API date/time validation)."""
    booking = services.create_booking(
        user=user,
        museum=museum,
        slot=slot or first_slot(museum),
        visit_date=visit_date or future_open_date(museum),
        items=[{"ticket_type": ticket(museum, ticket_name), "quantity": qty}],
        visitor_name=kw.pop("visitor_name", "Asha Rao"),
        visitor_email=kw.pop("visitor_email", user.email),
        visitor_phone=kw.pop("visitor_phone", PHONE),
        **kw,
    )
    if confirm and booking.status == Booking.Status.PENDING:
        services.confirm_payment(booking, method)
    booking.refresh_from_db()
    return booking


def age_booking(booking, minutes):
    """Move a booking's creation time into the past (e.g. to let its seat hold run out)."""
    Booking.objects.filter(pk=booking.pk).update(created_at=timezone.now() - datetime.timedelta(minutes=minutes))
    booking.refresh_from_db()
    return booking


def booking_payload(museum, slot, visit_date, qty=1, ticket_name="Indian adult", **extra):
    return {
        "museum": museum.slug,
        "slot": slot.id,
        "visit_date": str(visit_date),
        "items": [{"ticket_type": ticket(museum, ticket_name).id, "quantity": qty}],
        "visitor_name": "Asha Rao",
        "visitor_email": "asha@example.com",
        "visitor_phone": PHONE,
        **extra,
    }


class APITestCase(TestCase):
    """TestCase that clears the cache (DRF throttles live there) before every test."""

    def setUp(self):
        super().setUp()
        cache.clear()
