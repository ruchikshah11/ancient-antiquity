"""Seed sample light & sound shows with sessions for the next N days (default 14).

    python manage.py seed_events [--days 14] [--reset]

Safe to re-run: events are matched by slug and missing sessions are added (existing ones are kept).
Times and prices follow the published shows; staff should confirm them in Admin -> Events.
"""
import datetime
from decimal import Decimal

from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from events.models import Event, EventPrice, EventSession
from museums.models import Museum

# Shown to visitors; times/prices are based on the published shows but staff should confirm them in Admin -> Events.
NOTE = "Show times and prices can change on holidays and in the monsoon; please check your ticket before you travel."

SAMPLES = [
    {
        "museum": "red-fort-new-delhi",
        "slug": "red-fort-light-and-sound",
        "title": "Red Fort Light & Sound Show",
        "description": "The story of Delhi from the Mughal court to Independence, told in light and sound on the "
                       "walls of the Red Fort. " + NOTE,
        "language": "Hindi, English",
        "shows": [("18:30", "19:30", "Hindi"), ("19:45", "20:45", "English")],
        "prices": [("Adult", "80"), ("Child (under 12)", "30"), ("Foreign national", "300")],
        "closed_weekday": 0,  # Mondays, like the fort
    },
    {
        "museum": "amer-fort-jaipur",
        "slug": "amer-fort-light-and-sound",
        "title": "Amer Fort Light & Sound Show",
        "description": "Centuries of Kachhwaha history narrated against the ramparts of Amer Fort and Maota Lake. " + NOTE,
        "language": "Hindi, English",
        "shows": [("18:30", "19:20", "English"), ("19:30", "20:20", "Hindi")],
        "prices": [("Adult", "200"), ("Child (under 12)", "100"), ("Foreign national", "295")],
        "closed_weekday": None,
    },
    {
        "museum": "golconda-fort-hyderabad",
        "slug": "golconda-fort-light-and-sound",
        "title": "Golconda Fort Sound & Light Show",
        "description": "The rise of the Qutb Shahi kingdom and the legends of Golconda's diamonds, told after dark "
                       "inside the fort. " + NOTE,
        "language": "English, Telugu, Hindi",
        "shows": [("18:30", "19:25", "English"), ("19:45", "20:40", "Telugu / Hindi")],
        "prices": [("Adult", "140"), ("Child (under 12)", "110"), ("Foreign national", "250")],
        "closed_weekday": None,
    },
    {
        "museum": "archaeological-museum-purana-qila-new-delhi",
        "slug": "purana-qila-sound-and-light",
        "title": "Purana Qila Sound & Light Show",
        "description": "Ishq-e-Dilli: the many cities of Delhi projected on the walls of the Old Fort. " + NOTE,
        "language": "Hindi, English",
        "shows": [("19:00", "20:00", "Hindi"), ("20:15", "21:15", "English")],
        "prices": [("Adult", "100"), ("Child (under 12)", "50"), ("Foreign national", "500")],
        "closed_weekday": None,
    },
]


def _t(value):
    return datetime.datetime.strptime(value, "%H:%M").time()


class Command(BaseCommand):
    help = "Create 4 light & sound events with sessions for the next 60 days."

    def add_arguments(self, parser):
        parser.add_argument("--days", type=int, default=60)
        parser.add_argument("--capacity", type=int, default=150)
        parser.add_argument("--reset", action="store_true", help="Delete the sample events' unbooked future sessions first")

    @transaction.atomic
    def handle(self, *args, days, capacity, reset, **opts):
        today = timezone.localdate()
        for spec in SAMPLES:
            museum = Museum.objects.filter(slug=spec["museum"]).first()
            if not museum:
                self.stdout.write(self.style.WARNING(f"Skipped {spec['title']}: place {spec['museum']} not found"))
                continue
            event, created = Event.objects.get_or_create(
                slug=spec["slug"],
                defaults=dict(
                    museum=museum, title=spec["title"], kind=Event.Kind.LIGHT_SOUND,
                    description=spec["description"], language=spec["language"], image_url=museum.image_url,
                    duration_minutes=60, featured=True,
                ),
            )
            if not event.prices.exists():
                EventPrice.objects.bulk_create([
                    EventPrice(event=event, name=name, price=Decimal(price), sort=i)
                    for i, (name, price) in enumerate(spec["prices"])
                ])
            if reset:
                event.sessions.filter(date__gte=today, bookings__isnull=True).delete()
            have = set(event.sessions.values_list("date", "start_time"))
            new = []
            for offset in range(days):
                day = today + datetime.timedelta(days=offset)
                if spec["closed_weekday"] is not None and day.weekday() == spec["closed_weekday"]:
                    continue
                for start, end, _lang in spec["shows"]:
                    if (day, _t(start)) not in have:
                        new.append(EventSession(event=event, date=day, start_time=_t(start), end_time=_t(end),
                                                capacity=capacity))
            EventSession.objects.bulk_create(new)
            self.stdout.write(f"{'Created' if created else 'Updated'} {event.title}: +{len(new)} session(s)")
        self.stdout.write(self.style.SUCCESS("Done. Confirm times/prices in Admin -> Events."))
