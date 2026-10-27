"""Dynamic pricing suggestions from how full each weekday x slot has been over the last N weeks.

Data: ONE aggregate query, grouped in the database by (visit_date, slot) over the
(museum, visit_date, slot) index, so at most weeks x 7 x slots rows come back whatever the booking volume.
Python then folds those rows into weekday x slot cells. Day-level rows (rather than GROUP BY weekday) are what
let us (a) drop closed days and partially closed slots (PlaceClosure, Museum.closed_weekday), and
(b) tell "consistently busy" (most days over the line) from "one huge school trip".

Fill rate of a cell = visitors / (open days x slot capacity). Days with no bookings count as 0 % full.

A cell is
* busy  when its average fill >= 85 % AND at least 60 % of its open days were >= 85 % full;
* quiet when its average fill <= 25 % AND at least 60 % of its open days were <= 25 % full;
* needs at least 3 open days of data either way.

Suggested change of a cell:
* busy:  +10 % at 85 % full rising linearly to +20 % at 100 % (or more) full;
* quiet: -10 % at 25 % full rising linearly to -25 % at 0 % full.

museums.PriceRule has no slot dimension (a rule covers whole days), so suggestions are made per weekday: the
mean of that day's busy (or quiet) cells. The revenue estimate therefore covers EVERY slot of that weekday,
which is what the rule would actually change.

Revenue assumption (clearly an assumption): constant price elasticity E (default 0.5). A price change of p %
changes visitors by -E x p % (a 10 % rise loses 5 % of visitors; a 20 % cut adds 10 %), never above the slot's
capacity. Ticket revenue per visitor is the cell's own average (total + voucher - add-ons, over visitors), or
the place's average when the cell had no visitors.
"""
import datetime
from decimal import Decimal

from django.db.models import Sum

from bookings.models import Booking
from museums.models import Museum, PlaceClosure

BUSY_FILL = 0.85
QUIET_FILL = 0.25
CONSISTENT_SHARE = 0.6
MIN_DAYS = 3
PREMIUM_RANGE = (10, 20)
DISCOUNT_RANGE = (10, 25)
DEFAULT_ELASTICITY = 0.5
LIVE = (Booking.Status.CONFIRMED, Booking.Status.CHECKED_IN)
WEEKDAYS = [label for _, label in Museum.Weekday.choices]


def premium_percent(fill):
    low, high = PREMIUM_RANGE
    share = min(max((fill - BUSY_FILL) / (1 - BUSY_FILL), 0), 1)
    return round(low + (high - low) * share)


def discount_percent(fill):
    low, high = DISCOUNT_RANGE
    share = min(max((QUIET_FILL - fill) / QUIET_FILL, 0), 1)
    return round(low + (high - low) * share)


def classify(fills):
    """(status, suggested signed percent) for one cell from its per-open-day fill rates."""
    if len(fills) < MIN_DAYS:
        return "nodata", 0
    avg = sum(fills) / len(fills)
    if avg >= BUSY_FILL and sum(f >= BUSY_FILL for f in fills) / len(fills) >= CONSISTENT_SHARE:
        return "busy", premium_percent(avg)
    if avg <= QUIET_FILL and sum(f <= QUIET_FILL for f in fills) / len(fills) >= CONSISTENT_SHARE:
        return "quiet", -discount_percent(avg)
    return "normal", 0


def estimate(visitors_per_day, price, capacity, percent, elasticity):
    """(visitors now, visitors after, revenue now, revenue after) for one slot-day under the assumption."""
    change = percent / 100
    after = max(visitors_per_day * (1 - elasticity * change), 0)
    after = min(after, capacity) if capacity else after
    return visitors_per_day, after, visitors_per_day * price, after * price * (1 + change)


def closed_days(museum, start, end):
    """({closed date}, {date: {closed slot ids}}) between start and end (weekly closed day + closures)."""
    whole, partial = set(), {}
    day = start
    while day <= end:
        if museum.is_closed_on(day):
            whole.add(day)
        day += datetime.timedelta(days=1)
    for closure in PlaceClosure.covering(museum, start, end).prefetch_related("slots"):
        day = max(closure.start_date, start)
        last = min(closure.end_date, end)
        slot_ids = {s.id for s in closure.slots.all()}
        while day <= last:
            if closure.all_day:
                whole.add(day)
            else:
                partial.setdefault(day, set()).update(slot_ids)
            day += datetime.timedelta(days=1)
    return whole, partial


def pricing_suggestions(museum, today, weeks=12, elasticity=DEFAULT_ELASTICITY):
    end = today - datetime.timedelta(days=1)
    start = today - datetime.timedelta(days=7 * weeks)
    slots = list(museum.slots.filter(is_active=True).order_by("start_time", "id"))
    slot_ids = [s.id for s in slots]

    rows = (
        Booking.objects.filter(
            museum=museum, visit_date__gte=start, visit_date__lte=end, slot_id__in=slot_ids, status__in=LIVE,
        )
        .order_by()
        .values("visit_date", "slot_id")
        .annotate(
            visitors=Sum("total_visitors"), amount=Sum("total_amount"), voucher=Sum("voucher_amount"),
            addons=Sum("addons_amount"),
        )
    )
    by_day = {}
    for r in rows:
        ticket_revenue = (r["amount"] or 0) + (r["voucher"] or 0) - (r["addons"] or 0)
        by_day[(r["visit_date"], r["slot_id"])] = (r["visitors"] or 0, Decimal(ticket_revenue))

    whole, partial = closed_days(museum, start, end)

    # cells[(weekday, slot_id)] = {"fills": [...], "visitors": n, "revenue": Decimal, "days": n}
    cells = {(w, s.id): {"fills": [], "visitors": 0, "revenue": Decimal(0)} for w in range(7) for s in slots}
    day = start
    while day <= end:
        if day not in whole:
            for s in slots:
                if s.id in partial.get(day, ()):
                    continue
                visitors, revenue = by_day.get((day, s.id), (0, Decimal(0)))
                cell = cells[(day.weekday(), s.id)]
                cell["fills"].append(visitors / s.capacity)
                cell["visitors"] += visitors
                cell["revenue"] += revenue
        day += datetime.timedelta(days=1)

    total_visitors = sum(c["visitors"] for c in cells.values())
    total_revenue = sum((c["revenue"] for c in cells.values()), Decimal(0))
    place_price = float(total_revenue / total_visitors) if total_visitors else 0.0

    grid = []
    for w in range(7):
        row = {"weekday": w, "label": WEEKDAYS[w], "cells": []}
        for s in slots:
            c = cells[(w, s.id)]
            days = len(c["fills"])
            if not days:
                status, percent = "closed", 0
            else:
                status, percent = classify(c["fills"])
            avg = sum(c["fills"]) / days if days else None
            row["cells"].append({
                "slot": s.id,
                "days": days,
                "visitors": c["visitors"],
                "fill": round(avg, 3) if avg is not None else None,
                "busy_days": sum(f >= BUSY_FILL for f in c["fills"]),
                "quiet_days": sum(f <= QUIET_FILL for f in c["fills"]),
                "status": status,
                "suggested_percent": percent,
            })
        grid.append(row)

    suggestions = []
    for row in grid:
        w = row["weekday"]
        busy = [c for c in row["cells"] if c["status"] == "busy"]
        quiet = [c for c in row["cells"] if c["status"] == "quiet"]
        open_cells = [c for c in row["cells"] if c["days"]]
        for kind, chosen in (("premium", busy), ("discount", quiet)):
            if not chosen:
                continue
            percent = round(sum(c["suggested_percent"] for c in chosen) / len(chosen))
            now_v = after_v = now_r = after_r = 0.0
            for c in open_cells:
                slot = next(s for s in slots if s.id == c["slot"])
                cell = cells[(w, slot.id)]
                per_day = c["visitors"] / c["days"]
                price = float(cell["revenue"] / cell["visitors"]) if cell["visitors"] else place_price
                v0, v1, r0, r1 = estimate(per_day, price, slot.capacity, percent, elasticity)
                now_v, after_v, now_r, after_r = now_v + v0, after_v + v1, now_r + r0, after_r + r1
            label = WEEKDAYS[w]
            suggestions.append({
                "kind": kind,
                "weekday": w,
                "weekday_label": label,
                "percent": percent,
                "slots": [
                    {"slot": c["slot"], "fill": c["fill"], "suggested_percent": c["suggested_percent"]} for c in chosen
                ],
                "all_slots": len(chosen) == len(open_cells),
                # The same weekday also has slots pointing the other way: a whole-day rule can't fit both.
                "conflict": bool(busy and quiet),
                # One occurrence of the weekday per week.
                "visitors_per_week": {"current": round(now_v, 1), "estimated": round(after_v, 1)},
                "revenue_per_week": {
                    "current": round(now_r, 2), "estimated": round(after_r, 2), "change": round(after_r - now_r, 2),
                },
                "revenue_change_over_period": round((after_r - now_r) * weeks, 2),
                "rule": {
                    "museum": museum.slug,
                    "name": f"{label} {'peak premium' if kind == 'premium' else 'quiet-day discount'} "
                            f"{percent:+d}% (suggested)",
                    "weekdays": str(w),
                    "adjustment_type": "percent",
                    "value": str(percent),
                    # A trial as long as the period it was learnt from; review the effect afterwards.
                    "start_date": str(today + datetime.timedelta(days=1)),
                    "end_date": str(today + datetime.timedelta(days=7 * weeks)),
                    "priority": 0,
                    "is_active": True,
                },
            })

    return {
        "museum": {"slug": museum.slug, "name": museum.name},
        "weeks": weeks,
        "from": start,
        "to": end,
        "elasticity": elasticity,
        "thresholds": {
            "busy_fill": BUSY_FILL, "quiet_fill": QUIET_FILL, "consistent_share": CONSISTENT_SHARE, "min_days": MIN_DAYS,
            "premium_percent": list(PREMIUM_RANGE), "discount_percent": list(DISCOUNT_RANGE),
        },
        "assumption": (
            f"Estimate only. Assumes price elasticity of -{elasticity:g}: every 10% price rise loses "
            f"{elasticity * 10:g}% of visitors and every 10% cut adds {elasticity * 10:g}% (never above slot "
            "capacity). Price rules apply to the whole day, so the estimate covers every slot of that weekday."
        ),
        "average_ticket_revenue_per_visitor": round(place_price, 2),
        "slots": [
            {"id": s.id, "start_time": s.start_time, "end_time": s.end_time, "capacity": s.capacity} for s in slots
        ],
        "grid": grid,
        "suggestions": suggestions,
    }
