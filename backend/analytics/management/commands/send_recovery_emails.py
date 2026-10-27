"""Email visitors who started a booking but didn't pay: one friendly "your tickets are waiting" reminder.

Run every 15 minutes (cron):
    python manage.py send_recovery_emails
Picks unpaid online bookings created 30 minutes to 24 hours ago (see analytics/README.md). Each booking is reminded
at most once (RecoveryEmail), so re-running is safe. Also links earlier emails to the bookings they converted into.
"""
from django.core.management.base import BaseCommand

from analytics.recovery import candidates, mark_conversions, send_recovery_emails


class Command(BaseCommand):
    help = "Send one reminder email per abandoned (unpaid) online booking created 30 min - 24 h ago."

    def add_arguments(self, parser):
        parser.add_argument("--dry-run", action="store_true", help="List who would be emailed without sending.")

    def handle(self, *args, **opts):
        if opts["dry_run"]:
            for booking, email in candidates():
                self.stdout.write(f"{booking.reference}  {booking.museum.name}  {booking.visit_date}  -> {email}")
            return
        sent, failed, _ = send_recovery_emails()
        converted = mark_conversions()
        self.stdout.write(self.style.SUCCESS(
            f"Recovery emails: {sent} sent, {failed} failed; {converted} newly marked converted."
        ))
