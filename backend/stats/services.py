"""Computing, refreshing and reading DailyStat.

Freshness rules (all lazy, on read):
- a day is recomputed when it is marked dirty (a booking created/changed/deleted on it, see signals.py);
- today and yesterday are recomputed when their figures are older than STATS_FRESH_SECONDS (about 2 minutes),
  which also covers bulk `.update()` calls that fire no signals (e.g. expiring unpaid holds);
- report ranges compute any day that was never computed;
- `manage.py rebuild_stats` recomputes everything (or a range); a nightly task redoes the last 2 days.
"""
import datetime
import logging
import threading
from decimal import Decimal

from django.conf import settings
from django.db import connection, transaction
from django.db.models import Count, Q, Sum
from django.utils import timezone

from ancient_antiquity.dates import day_range
from bookings.models import Booking
from museums.models import Museum

from .models import DailyStat, StatDay, StatusGroup

log = logging.getLogger(__name__)

ZERO = Decimal("0.00")
PAID_STATUSES = (Booking.Status.CONFIRMED, Booking.Status.CHECKED_IN)
PAID_Q = Q(status_group=StatusGroup.PAID)
MONEY = ("revenue", "refunds", "discounts", "addons", "membership_discounts")
COUNTS = ("bookings", "checked_in_bookings", "visitors", "visit_bookings", "visit_visitors", "visit_checked_in_visitors")


def fresh_seconds():
    return getattr(settings, "STATS_FRESH_SECONDS", 120)


def status_group(status):
    if status in PAID_STATUSES:
        return StatusGroup.PAID
    if status in StatusGroup.values:
        return status
    return StatusGroup.PENDING


def local_date(moment):
    return timezone.localtime(moment).date()


# ------------------------------------------------------------------ dirty marking

def mark_dirty(dates):
    """Flag days whose DailyStat rows no longer match the bookings (refreshed lazily on the next read)."""
    dates = {d for d in dates if d is not None}
    if not dates:
        return
    now = timezone.now()
    StatDay.objects.bulk_create(
        [StatDay(date=d, dirty_since=now) for d in sorted(dates)],
        update_conflicts=True, unique_fields=["date"], update_fields=["dirty_since"],
    )


def mark_dirty_after_commit(dates):
    """Mark now (so this transaction's own reads see it) and again after commit, so a refresh that ran
    concurrently on a snapshot without this change cannot clear the flag (PostgreSQL)."""
    dates = set(dates)
    mark_dirty(dates)
    if connection.in_atomic_block:
        transaction.on_commit(lambda: mark_dirty(dates))


def expire_stale_bookings():
    """bookings.services.expire_stale_bookings() uses .update() (no signals): mark the affected days first."""
    from bookings import services as booking_services

    stale = Booking.objects.filter(status=Booking.Status.PENDING).filter(
        Q(pay_by__isnull=True, created_at__lt=booking_services.hold_cutoff()) | Q(pay_by__lte=timezone.now())
    )
    dates = set()
    for created, visit in stale.values_list("created_at", "visit_date")[:5000]:
        dates.update((local_date(created), visit))
    if dates:
        mark_dirty(dates)
    booking_services.expire_stale_bookings()


# ------------------------------------------------------------------ computing

def _key(row):
    return (row["museum_id"], row["channel"], row["is_group"], status_group(row["status"]))


def day_rows(day):
    """DailyStat objects for one day: two set-based GROUP BY queries (sale date range, visit date)."""
    start, end = day_range(day, day)
    rows = {}

    def get(key):
        if key not in rows:
            rows[key] = DailyStat(
                date=day, museum_id=key[0], channel=key[1], is_group=key[2], status_group=key[3],
                **{f: 0 for f in COUNTS}, **{f: ZERO for f in MONEY},
            )
        return rows[key]

    created = (
        Booking.objects.filter(created_at__gte=start, created_at__lt=end).order_by()
        .values("museum_id", "channel", "is_group", "status")
        .annotate(
            n=Count("id"), v=Sum("total_visitors"), rev=Sum("total_amount"),
            ref=Sum("refund_amount", filter=Q(refund_amount__gt=0)), disc=Sum("discount_amount"),
            add=Sum("addons_amount"), mem=Sum("membership_discount"),
        )
    )
    for r in created:
        s = get(_key(r))
        s.bookings += r["n"]
        if r["status"] == Booking.Status.CHECKED_IN:
            s.checked_in_bookings += r["n"]
        s.visitors += r["v"] or 0
        s.revenue += r["rev"] or ZERO
        s.refunds += r["ref"] or ZERO
        s.discounts += r["disc"] or ZERO
        s.addons += r["add"] or ZERO
        s.membership_discounts += r["mem"] or ZERO

    visits = (
        Booking.objects.filter(visit_date=day).order_by()
        .values("museum_id", "channel", "is_group", "status")
        .annotate(n=Count("id"), v=Sum("total_visitors"))
    )
    for r in visits:
        s = get(_key(r))
        s.visit_bookings += r["n"]
        s.visit_visitors += r["v"] or 0
        if r["status"] == Booking.Status.CHECKED_IN:
            s.visit_checked_in_visitors += r["v"] or 0
    return list(rows.values())


def compute_day(day):
    """Replace one day's DailyStat rows. Returns the number of rows written."""
    started = timezone.now()
    rows = day_rows(day)  # reads outside the write transaction (SQLite: keeps the write lock short)
    with transaction.atomic():
        # Write first so SQLite takes the write lock at once; on PostgreSQL the row lock serialises refreshes.
        StatDay.objects.bulk_create([StatDay(date=day)], ignore_conflicts=True)
        list(StatDay.objects.select_for_update().filter(date=day).values_list("pk", flat=True))
        _write_changes(day, rows)
        StatDay.objects.filter(date=day).update(refreshed_at=started)
        StatDay.objects.filter(date=day, dirty_since__lte=started).update(dirty_since=None)
    return len(rows)


def _write_changes(day, rows):
    """Make the day's stored rows equal `rows`, writing only what differs (usually a few rows for today)."""
    key = lambda s: (s.museum_id, s.channel, s.is_group, s.status_group)  # noqa: E731
    fields = COUNTS + MONEY
    existing = {key(s): s for s in DailyStat.objects.filter(date=day)}
    wanted = {key(s): s for s in rows}
    stale = [s.pk for k, s in existing.items() if k not in wanted]
    new = [s for k, s in wanted.items() if k not in existing]
    changed = []
    for k, s in wanted.items():
        old = existing.get(k)
        if old is not None and any(getattr(old, f) != getattr(s, f) for f in fields):
            for f in fields:
                setattr(old, f, getattr(s, f))
            changed.append(old)
    if stale:
        DailyStat.objects.filter(pk__in=stale).delete()
    if new:
        DailyStat.objects.bulk_create(new, batch_size=500)
    for s in changed:  # few rows: one small UPDATE each beats bulk_update's CASE expressions
        DailyStat.objects.filter(pk=s.pk).update(**{f: getattr(s, f) for f in fields})


def rebuild(first, last, progress=None):
    """Recompute every day from first to last (inclusive). Returns (days, rows)."""
    day, days, total = first, 0, 0
    while day <= last:
        total += compute_day(day)
        days += 1
        if progress:
            progress(day, days, total)
        day += datetime.timedelta(days=1)
    return days, total


def booking_date_bounds():
    """(first, last) day that any booking touches (sale or visit date), or None when there are none."""
    from django.db.models import Max, Min

    b = Booking.objects.aggregate(c0=Min("created_at"), c1=Max("created_at"), v0=Min("visit_date"), v1=Max("visit_date"))
    if b["c0"] is None:
        return None
    return min(local_date(b["c0"]), b["v0"]), max(local_date(b["c1"]), b["v1"])


def ensure_fresh(first=None, last=None, all_dirty=False):
    """Recompute what a read of first..last needs (see module docstring). Returns the days recomputed."""
    today = timezone.localdate()
    cutoff = timezone.now() - datetime.timedelta(seconds=fresh_seconds())
    in_range = (lambda d: True) if first is None else (lambda d: first <= d <= last)

    days = StatDay.objects.filter(dirty_since__isnull=False)
    if not all_dirty and first is not None:
        days = days.filter(date__gte=first, date__lte=last)
    need = set(days.values_list("date", flat=True))

    recent = [d for d in (today, today - datetime.timedelta(days=1)) if in_range(d)]
    timed_out = set()
    if recent:
        known = dict(StatDay.objects.filter(date__in=recent).values_list("date", "refreshed_at"))
        need.update(d for d in recent if not known.get(d))
        timed_out = {d for d in recent if known.get(d) and known[d] < cutoff} - need

    if first is not None:
        upto = min(last, today)
        if first <= upto:
            have = set(
                StatDay.objects.filter(date__gte=first, date__lte=upto, refreshed_at__isnull=False)
                .values_list("date", flat=True)
            )
            day = first
            while day <= upto:
                if day not in have:
                    need.add(day)
                day += datetime.timedelta(days=1)

    for day in sorted(need):
        compute_day(day)
    if timed_out:
        if connection.in_atomic_block:  # inside a transaction (tests, management code): stay synchronous
            for day in sorted(timed_out):
                compute_day(day)
        else:
            refresh_in_background(timed_out)
    return sorted(need | timed_out)


_refreshing = set()
_refreshing_lock = threading.Lock()


def refresh_in_background(days):
    """Timer refresh of today/yesterday without making the request wait (yesterday can hold ~2 lakh bookings).
    Dirty and never-computed days are always recomputed before the read; these only lag the 2-minute timer."""
    with _refreshing_lock:
        days = sorted(set(days) - _refreshing)
        _refreshing.update(days)
    if not days:
        return

    def run():
        try:
            for day in days:
                compute_day(day)
        except Exception:
            log.exception("Background stats refresh failed for %s", days)
        finally:
            with _refreshing_lock:
                _refreshing.difference_update(days)
            connection.close()

    threading.Thread(target=run, name="stats-refresh", daemon=True).start()


# ------------------------------------------------------------------ reading

def panel_stats(user):
    """DailyStat rows a panel user may see (same scoping as bookings.views.panel_bookings)."""
    from rest_framework.exceptions import PermissionDenied

    from bookings.views import NOT_ASSIGNED

    if user.is_admin_role:
        return DailyStat.objects.all()
    museums = Museum.for_panel_user(user)
    if not museums.exists():
        raise PermissionDenied(f"{NOT_ASSIGNED} Ask an administrator to assign you to a place.")
    return DailyStat.objects.filter(museum__in=museums)


def _renamed(rows, names):
    return [{names.get(k, k): v for k, v in r.items()} for r in rows]


def report_summary(rows, date_from, date_to):
    """(daily, splits, by_museum) for ReportSummaryView (money unrounded). Two scans of the range:

    - one GROUP BY (date, channel, is_group) with conditional sums, folded in Python into the daily rows
      (and so the totals) and the channel / individual-vs-group splits;
    - one GROUP BY museum over paid rows with bookings.
    Aggregates use s_* aliases (an alias equal to a field name would shadow it) and are renamed back."""
    rows = rows.filter(date__gte=date_from, date__lte=date_to)
    names = {"s_bookings": "bookings", "s_visitors": "visitors", "s_revenue": "revenue", "s_refunds": "refunds",
             "s_discounts": "discounts", "s_addons": "addons", "s_membership": "membership", "s_cancelled": "cancelled"}
    groups = _renamed(rows.order_by().values("date", "channel", "is_group").annotate(
        s_bookings=Sum("bookings", filter=PAID_Q), s_visitors=Sum("visitors", filter=PAID_Q),
        s_revenue=Sum("revenue", filter=PAID_Q), s_refunds=Sum("refunds"),
        s_discounts=Sum("discounts", filter=PAID_Q), s_addons=Sum("addons", filter=PAID_Q),
        s_membership=Sum("membership_discounts", filter=PAID_Q),
        s_cancelled=Sum("bookings", filter=Q(status_group=StatusGroup.CANCELLED)),
    ), names)
    daily, splits = {}, {}
    for g in groups:
        day = daily.setdefault(g["date"], {})
        for field in names.values():
            day[field] = day.get(field, 0) + (g[field] or 0)
        split = splits.setdefault((g["channel"], g["is_group"]), {
            "channel": g["channel"], "is_group": g["is_group"], "bookings": 0, "visitors": 0, "revenue": ZERO,
        })
        for field in ("bookings", "visitors", "revenue"):
            split[field] += g[field] or 0
    paid = rows.filter(PAID_Q, bookings__gt=0).order_by()
    sums = dict(s_bookings=Sum("bookings"), s_visitors=Sum("visitors"), s_revenue=Sum("revenue"))
    by_museum = _renamed(paid.values("museum_id").annotate(**sums), names)
    return daily, list(splits.values()), by_museum


def museum_info(ids):
    return {
        m["id"]: m
        for m in Museum.objects.filter(id__in=list(ids)).values("id", "slug", "name", "city__name", "city__state__name")
    }
