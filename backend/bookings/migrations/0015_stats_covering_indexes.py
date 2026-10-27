"""Covering indexes for stats.DailyStat: recomputing one day (stats.services.day_rows) reads only these, never
the scattered booking rows (a cold day took seconds on ~11 lakh bookings; with them, milliseconds).

Plain SQL that SQLite and PostgreSQL both accept. They are deliberately not in Booking.Meta (they serve the
stats app only), so Django's model state does not track them.
"""
from django.db import migrations

CREATED = (
    "CREATE INDEX IF NOT EXISTS booking_stats_created_idx ON bookings_booking "
    "(created_at, museum_id, channel, is_group, status, total_visitors, total_amount, refund_amount, "
    "discount_amount, addons_amount, membership_discount)"
)
VISIT = (
    "CREATE INDEX IF NOT EXISTS booking_stats_visit_idx ON bookings_booking "
    "(visit_date, museum_id, channel, is_group, status, total_visitors)"
)


class Migration(migrations.Migration):
    dependencies = [("bookings", "0014_booking_search")]

    operations = [
        migrations.RunSQL(CREATED, "DROP INDEX IF EXISTS booking_stats_created_idx", elidable=False),
        migrations.RunSQL(VISIT, "DROP INDEX IF EXISTS booking_stats_visit_idx", elidable=False),
    ]
