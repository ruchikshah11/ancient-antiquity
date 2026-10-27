"""Reference implementations: the dashboard and report figures computed straight from bookings, exactly as
DashboardView / ReportSummaryView did before they read stats.DailyStat. Used by the tests and by
`manage.py compare_stats` to prove the pre-calculated figures match. Slow on lakhs of bookings by design."""
import datetime

from django.contrib.auth import get_user_model
from django.db.models import Count, Q, Sum
from django.db.models.functions import TruncDate

from ancient_antiquity.dates import day_range, day_start
from bookings.models import Booking
from bookings.reports import _money
from bookings.views import PAID, panel_bookings
from museums.models import Museum


def report(user, date_from, date_to, museum=None):
    start, end = day_range(date_from, date_to)
    qs = panel_bookings(user).filter(created_at__gte=start, created_at__lt=end)
    if museum:
        qs = qs.filter(museum=museum)
    paid = qs.filter(status__in=PAID)
    sums = dict(bookings=Count("id"), visitors=Sum("total_visitors"), revenue=Sum("total_amount"))
    paid_by_day = {
        r["day"]: r for r in paid.annotate(day=TruncDate("created_at")).values("day").annotate(**sums).order_by()
    }
    refunds_by_day = {
        r["day"]: r["refunds"]
        for r in qs.filter(refund_amount__gt=0).annotate(day=TruncDate("created_at")).values("day")
        .annotate(refunds=Sum("refund_amount")).order_by()
    }
    daily = []
    day = date_from
    while day <= date_to:
        row = paid_by_day.get(day, {})
        daily.append({
            "date": day, "bookings": row.get("bookings", 0), "visitors": row.get("visitors") or 0,
            "revenue": _money(row.get("revenue")), "refunds": _money(refunds_by_day.get(day)),
        })
        day += datetime.timedelta(days=1)
    t = paid.aggregate(**sums, discounts=Sum("discount_amount"), addons=Sum("addons_amount"),
                       membership=Sum("membership_discount"))
    other = qs.aggregate(refunds=Sum("refund_amount"), cancelled=Count("id", filter=Q(status=Booking.Status.CANCELLED)))
    totals = {
        "bookings": t["bookings"] or 0, "visitors": t["visitors"] or 0, "revenue": _money(t["revenue"]),
        "refunds": _money(other["refunds"]), "discounts": _money(t["discounts"]), "addons": _money(t["addons"]),
        "membership_discounts": _money(t["membership"]), "cancelled": other["cancelled"],
    }
    totals["net"] = totals["revenue"]

    def split(field, labels):
        rows = {r[field]: r for r in paid.order_by().values(field).annotate(**sums)}
        return [
            {"key": key, "label": label, "bookings": rows.get(key, {}).get("bookings", 0),
             "visitors": rows.get(key, {}).get("visitors") or 0, "revenue": _money(rows.get(key, {}).get("revenue"))}
            for key, label in labels
        ]

    by_museum = [
        {"slug": r["museum__slug"], "name": r["museum__name"], "city": r["museum__city__name"],
         "state": r["museum__city__state__name"], "bookings": r["bookings"], "visitors": r["visitors"] or 0,
         "revenue": _money(r["revenue"])}
        for r in paid.order_by().values("museum__slug", "museum__name", "museum__city__name", "museum__city__state__name")
        .annotate(**sums).order_by("-revenue", "museum__name")
    ]
    return {
        "totals": totals, "daily": daily,
        "by_channel": split("channel", Booking.Channel.choices),
        "by_type": split("is_group", [(False, "Individual"), (True, "Group")]),
        "by_museum": by_museum,
    }


def dashboard(user, today):
    start = today - datetime.timedelta(days=13)
    scoped = panel_bookings(user)
    paid = scoped.filter(status__in=PAID)
    totals = paid.aggregate(revenue=Sum("total_amount"), visitors=Sum("total_visitors"), bookings=Count("id"))
    expected = paid.filter(visit_date=today).aggregate(n=Sum("total_visitors"))["n"] or 0
    checked_in = scoped.filter(visit_date=today, status=Booking.Status.CHECKED_IN).aggregate(n=Sum("total_visitors"))["n"] or 0
    by_day = {
        r["day"]: r for r in paid.filter(created_at__gte=day_start(start)).annotate(day=TruncDate("created_at"))
        .values("day").annotate(bookings=Count("id"), revenue=Sum("total_amount"))
    }
    daily = []
    for offset in range(14):
        day = start + datetime.timedelta(days=offset)
        row = by_day.get(day, {})
        daily.append({"date": day, "bookings": row.get("bookings", 0), "revenue": row.get("revenue") or 0})
    top_museums = [
        {"name": r["museum__name"], "slug": r["museum__slug"], "revenue": r["revenue"], "visitors": r["visitors"]}
        for r in paid.values("museum__name", "museum__slug")
        .annotate(revenue=Sum("total_amount"), visitors=Sum("total_visitors")).order_by("-revenue")[:8]
    ]
    by_state = [
        {"state": r["museum__city__state__name"], "visitors": r["visitors"], "revenue": r["revenue"]}
        for r in paid.values("museum__city__state__name")
        .annotate(visitors=Sum("total_visitors"), revenue=Sum("total_amount")).order_by("-visitors")[:10]
    ]
    status_counts = dict(scoped.order_by().values("status").annotate(n=Count("id")).values_list("status", "n"))
    by_channel = {
        r["channel"]: {"bookings": r["bookings"], "revenue": r["revenue"] or 0, "visitors": r["visitors"] or 0}
        for r in paid.order_by().values("channel").annotate(
            bookings=Count("id"), revenue=Sum("total_amount"), visitors=Sum("total_visitors"))
    }
    groups = paid.filter(is_group=True).aggregate(n=Count("id"), visitors=Sum("total_visitors"))
    return {
        "totals": {
            "revenue": totals["revenue"] or 0, "visitors": totals["visitors"] or 0, "bookings": totals["bookings"] or 0,
            "expected_today": expected, "checked_in_today": checked_in,
            "museums": Museum.for_panel_user(user).filter(is_active=True).count(),
            "users": get_user_model().objects.count(),
            "group_bookings": groups["n"] or 0, "group_visitors": groups["visitors"] or 0,
        },
        "daily": daily, "top_museums": top_museums, "by_state": by_state,
        "status_counts": status_counts, "by_channel": by_channel,
    }


def differences(new, old, path=""):
    """List of 'path: new != old' for two nested dicts/lists, comparing numbers by value."""
    from decimal import Decimal

    out = []
    if isinstance(old, dict):
        for key in set(old) | set(new or {}):
            out += differences((new or {}).get(key), old.get(key), f"{path}.{key}")
    elif isinstance(old, list):
        if len(old) != len(new or []):
            return [f"{path}: {len(new or [])} items != {len(old)}"]
        for i, (a, b) in enumerate(zip(new, old)):
            out += differences(a, b, f"{path}[{i}]")
    elif (isinstance(old, (int, float, Decimal)) and isinstance(new, (int, float, Decimal))
          and not isinstance(old, bool) and not isinstance(new, bool)):
        if Decimal(str(new)) != Decimal(str(old)):
            out.append(f"{path}: {new} != {old}")
    elif new != old:
        out.append(f"{path}: {new!r} != {old!r}")
    return out
