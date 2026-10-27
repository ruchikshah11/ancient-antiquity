"""Remind visitors of upcoming visits by email, SMS, WhatsApp and web push.

Run once a day (cron, e.g. 18:00 IST) for next-day reminders:
    python manage.py send_visit_reminders
Optionally also hourly for "starts soon" reminders:
    python manage.py send_visit_reminders --hours-before 2

Each booking gets each reminder kind at most once (tracked in NotificationLog), so re-running is safe.
"""
from datetime import date, timedelta

from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from bookings.models import Booking
from notifications import services


class Command(BaseCommand):
    help = "Send visit reminders (day before; or N hours before the slot with --hours-before)."

    def add_arguments(self, parser):
        parser.add_argument("--hours-before", type=float, default=None,
                            help="Remind bookings whose slot starts within the next N hours (kind reminder_soon).")
        parser.add_argument("--date", default=None,
                            help="Visit date to remind (YYYY-MM-DD); default tomorrow. Ignored with --hours-before.")
        parser.add_argument("--dry-run", action="store_true", help="List the bookings without sending anything.")

    def handle(self, *args, **opts):
        qs = Booking.objects.filter(status=Booking.Status.CONFIRMED).select_related("museum", "slot")
        hours = opts["hours_before"]
        if hours is not None:
            if hours <= 0:
                raise CommandError("--hours-before must be positive")
            kind = services.KIND_REMINDER_SOON
            now = timezone.now()
            until = now + timedelta(hours=hours)
            candidates = qs.filter(visit_date__gte=timezone.localdate(now), visit_date__lte=timezone.localdate(until))
            bookings = [b for b in candidates if now <= b.slot_starts_at <= until]
        else:
            kind = services.KIND_REMINDER
            try:
                day = date.fromisoformat(opts["date"]) if opts["date"] else timezone.localdate() + timedelta(days=1)
            except ValueError:
                raise CommandError("--date must be YYYY-MM-DD")
            bookings = list(qs.filter(visit_date=day))

        sent = skipped = 0
        for booking in bookings:
            if services.reminder_already_sent(booking, kind):
                skipped += 1
                continue
            if opts["dry_run"]:
                self.stdout.write(f"would remind {booking.reference} ({booking.museum.name}, {booking.visit_date})")
                sent += 1
                continue
            try:
                if services.send_visit_reminder(booking, kind):
                    sent += 1
                else:
                    skipped += 1
            except Exception as exc:  # one bad booking must not stop the rest
                self.stderr.write(f"{booking.reference}: {exc}")
        verb = "would send" if opts["dry_run"] else "sent"
        self.stdout.write(self.style.SUCCESS(f"{kind}: {verb} {sent}, already reminded {skipped}"))
