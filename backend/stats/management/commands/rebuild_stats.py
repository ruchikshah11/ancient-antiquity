import datetime
import time

from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone
from django.utils.dateparse import parse_date

from stats import services


class Command(BaseCommand):
    help = (
        "Recompute the pre-calculated daily booking statistics (stats.DailyStat). Without options: every day "
        "that has bookings (sale or visit date). --days N: the last N days up to today (the nightly task uses 2)."
    )

    def add_arguments(self, parser):
        parser.add_argument("--from", dest="date_from", help="First day, YYYY-MM-DD")
        parser.add_argument("--to", dest="date_to", help="Last day, YYYY-MM-DD (default: today, or the last visit date)")
        parser.add_argument("--days", type=int, help="Only the last N days up to today")

    def handle(self, *args, date_from=None, date_to=None, days=None, **options):
        today = timezone.localdate()
        if days:
            first, last = today - datetime.timedelta(days=days - 1), today
        else:
            bounds = services.booking_date_bounds()
            first = parse_date(date_from) if date_from else (bounds[0] if bounds else today)
            last = parse_date(date_to) if date_to else (max(bounds[1], today) if bounds else today)
            if not first or not last:
                raise CommandError("Dates must be YYYY-MM-DD.")
        if first > last:
            raise CommandError("--from must be on or before --to.")
        started = time.monotonic()
        verbosity = options.get("verbosity", 1)

        def progress(day, n, rows):
            if verbosity > 1 or (verbosity and n % 50 == 0):
                self.stdout.write(f"  {day}: {n} days, {rows} rows so far")

        n_days, n_rows = services.rebuild(first, last, progress)
        self.stdout.write(self.style.SUCCESS(
            f"Rebuilt {n_days} days ({first} to {last}), {n_rows} rows in {time.monotonic() - started:.1f}s."
        ))
