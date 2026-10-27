"""Add India's national holidays as all-place closures for the admin to review.

    python manage.py seed_holidays            # 2026
    python manage.py seed_holidays --year 2027

Many monuments stay open on national holidays, so each entry is marked "verify with each place": review the
list under Admin > Closures and delete or narrow any that don't apply. Safe to run twice.
"""
import datetime

from django.core.management.base import BaseCommand

from museums.models import PlaceClosure

NATIONAL_HOLIDAYS = (
    (1, 26, "Republic Day"),
    (8, 15, "Independence Day"),
    (10, 2, "Gandhi Jayanti"),
)
REASON = "National holiday (verify with each place)"


class Command(BaseCommand):
    help = "Add India's national holidays (Republic Day, Independence Day, Gandhi Jayanti) as all-place closures."

    def add_arguments(self, parser):
        parser.add_argument("--year", type=int, default=2026)

    def handle(self, *args, year, **options):
        created = 0
        for month, day, name in NATIONAL_HOLIDAYS:
            date = datetime.date(year, month, day)
            reason = f"{name}: {REASON}"
            _, new = PlaceClosure.objects.get_or_create(
                museum=None, start_date=date, end_date=date, reason=reason, defaults={"all_day": True},
            )
            created += new
            self.stdout.write(f"{'Added' if new else 'Already there'}: {date:%d %b %Y} {name}")
        self.stdout.write(self.style.SUCCESS(f"{created} closure(s) added for {year}. Review them in Admin > Closures."))
