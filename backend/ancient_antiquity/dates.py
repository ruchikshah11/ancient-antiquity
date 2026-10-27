"""Date ranges as datetimes, so filters on DateTimeFields can use their indexes.

`created_at__date__gte=day` makes SQLite run a Python function on every row (a full scan of the bookings
table); `created_at__gte=day_start(day)` is an index range. Use these for every "by day" filter.
"""
import datetime

from django.utils import timezone


def day_start(day):
    """Midnight at the start of `day` in the site's time zone (aware)."""
    return timezone.make_aware(datetime.datetime.combine(day, datetime.time.min))


def day_range(first, last):
    """(start, end) covering every moment of first..last: use as field__gte=start, field__lt=end."""
    return day_start(first), day_start(last + datetime.timedelta(days=1))
