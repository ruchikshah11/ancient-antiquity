"""Give well-known places a virtual tour link (Google Street View, opened through the documented Maps URLs API).

Google photographed these ASI monuments for Street View (Google / Archaeological Survey of India, 2015 onwards).
`map_action=pano&viewpoint=lat,lng` opens the panorama nearest to the point, so the links don't depend on
panorama ids that can change. Only places in the database are touched; existing links are kept unless --force.

    python manage.py seed_virtual_tours [--force] [--dry-run]
"""
from django.core.management.base import BaseCommand

from museums.models import Museum

STREET_VIEW = "https://www.google.com/maps/@?api=1&map_action=pano&viewpoint={lat},{lng}"

# slug -> (latitude, longitude) of a public viewpoint inside / in front of the monument
TOURS = {
    "taj-mahal-agra": (27.1751, 78.0421),
    "red-fort-new-delhi": (28.6562, 77.2410),
    "qutub-minar-new-delhi": (28.5245, 77.1855),
    "humayuns-tomb-new-delhi": (28.5933, 77.2507),
    "agra-fort-agra": (27.1795, 78.0211),
    "fatehpur-sikri-fatehpur-sikri": (27.0945, 77.6679),
    "group-of-monuments-at-hampi-hampi": (15.3426, 76.4747),
    "konark-sun-temple-konark": (19.8876, 86.0945),
    "group-of-monuments-at-mahabalipuram-mamallapuram": (12.6165, 80.1993),
    "rani-ki-vav-patan": (23.8589, 72.1016),
    "charminar-hyderabad": (17.3616, 78.4747),
}


class Command(BaseCommand):
    help = "Set Google Street View virtual tour links for well-known monuments in the database."

    def add_arguments(self, parser):
        parser.add_argument("--force", action="store_true", help="Replace links an admin has already set")
        parser.add_argument("--dry-run", action="store_true", help="Show what would change without saving")

    def handle(self, *args, force=False, dry_run=False, **options):
        updated = skipped = 0
        museums = {m.slug: m for m in Museum.objects.filter(slug__in=TOURS)}
        for slug, (lat, lng) in TOURS.items():
            museum = museums.get(slug)
            if not museum:
                continue
            url = STREET_VIEW.format(lat=lat, lng=lng)
            if museum.virtual_tour_url and not force:
                skipped += 1
                continue
            if museum.virtual_tour_url == url and museum.virtual_tour_kind == Museum.VirtualTourKind.STREET_VIEW:
                skipped += 1
                continue
            museum.virtual_tour_url = url
            museum.virtual_tour_kind = Museum.VirtualTourKind.STREET_VIEW
            if not dry_run:
                museum.save(update_fields=["virtual_tour_url", "virtual_tour_kind", "updated_at"])
            updated += 1
            self.stdout.write(f"  {museum.name}: {url}")
        missing = len(TOURS) - len(museums)
        verb = "Would set" if dry_run else "Set"
        self.stdout.write(self.style.SUCCESS(
            f"{verb} {updated} virtual tour(s); {skipped} already had one; {missing} place(s) not in the database."
        ))
