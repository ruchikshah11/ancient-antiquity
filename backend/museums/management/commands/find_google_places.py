"""Match places that have no photo of their own to Google Maps, so the site can show Google photos for them.

    python manage.py find_google_places              # places without a photo and not matched yet
    python manage.py find_google_places --all        # also retry places that found no match before
    python manage.py find_google_places --dry-run    # show the matches without saving

Needs GOOGLE_MAPS_API_KEY in backend/.env (Places API (New)). Only the Google place ID is stored (allowed by
Google's terms); photos are fetched when shown. Each lookup is one Text Search request (about 1,250 places ~ a
one-off few hundred rupees after the free allowance). Matches need the place's own name words and, when the place
has coordinates, a Google location within 15 km. A place with google_place_name "-" was looked up and not found.
"""
import time

from django.core.management.base import BaseCommand, CommandError

from museums import google_places
from museums.models import Museum


class Command(BaseCommand):
    help = "Find the Google Maps place (for photos) of every place without a photo of its own"

    def add_arguments(self, parser):
        parser.add_argument("--all", action="store_true", help="Also retry places with no match last time")
        parser.add_argument("--dry-run", action="store_true", help="Print matches without saving")
        parser.add_argument("--limit", type=int, default=0, help="Stop after N places")

    def handle(self, *args, all=False, dry_run=False, limit=0, **opts):
        if not google_places.enabled():
            raise CommandError("Set GOOGLE_MAPS_API_KEY in backend/.env first (Google Cloud > Places API (New)).")
        qs = Museum.objects.filter(image_url="", images__isnull=True, google_place_id="").select_related("city__state")
        if not all:
            qs = qs.exclude(google_place_name="-")
        places = list(qs.order_by("pk"))
        if limit:
            places = places[:limit]
        self.stdout.write(f"Looking up {len(places)} places on Google Maps…")
        found = 0
        for n, m in enumerate(places, 1):
            try:
                match = google_places.find_place(m)
            except Exception as exc:  # quota / network: stop cleanly, re-run continues where it left off
                raise CommandError(f"Google lookup failed at {m.name}: {exc}") from exc
            if match:
                found += 1
                self.stdout.write(f"  [{n}/{len(places)}] {m.name} -> {match['name']}")
            else:
                self.stdout.write(f"  [{n}/{len(places)}] {m.name}: no match")
            if not dry_run:
                Museum.objects.filter(pk=m.pk).update(
                    google_place_id=match["id"] if match else "",
                    google_place_name=(match["name"] if match else "-")[:200],
                )
            time.sleep(0.05)
        left = Museum.objects.filter(image_url="", images__isnull=True, google_place_id="").count()
        self.stdout.write(self.style.SUCCESS(f"Matched {found} of {len(places)}. Places still without any photo: {left}"))
