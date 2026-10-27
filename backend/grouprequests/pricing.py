"""Date-based prices and closures for large group requests.

Uses the same rules as normal bookings: bookings.services.effective_price (PriceRule: weekend, holiday,
season) and the closures calendar (weekly closed day + PlaceClosure).
"""
from decimal import ROUND_HALF_UP, Decimal

from bookings import services
from museums.models import PriceRule


def closed_message(museum, day):
    """Why the whole place is closed on `day` (weekly closed day or a whole-day closure), or None if open."""
    if museum.is_closed_on(day):
        return f"{museum.name} is closed on {day:%A}s. Please pick another date."
    info = museum.closure_on(day)
    if info["closed"]:
        return f"{museum.name} is closed on {day:%d %b %Y}: {info['reason']}. Please pick another date."
    return None


def closed_info(museum, day):
    """(weekly_closed_day, closure_reason) for `day`: what the visitor UI needs to explain a closed date."""
    if museum.is_closed_on(day):
        return True, ""
    info = museum.closure_on(day)
    return False, info["reason"] if info["closed"] else ""


def slot_closures(museum, day):
    """{slot_id: reason} for slots closed on `day` by a partial closure."""
    return museum.closure_on(day)["slots"]


def ticket_prices(museum, day):
    """Every active ticket of the place with its effective price on `day`."""
    rules = list(PriceRule.objects.filter(museum=museum, is_active=True).order_by("-priority", "-id"))
    out = []
    for ticket in museum.ticket_types.filter(is_active=True):
        price, rule = services.effective_price(ticket, day, rules)
        out.append({"id": ticket.id, "name": ticket.name, "base_price": ticket.price, "price": price,
                    "rule": rule.name if rule else None})
    return out


def quote(museum, day, participants, group_type, ticket=None, discount_percent=None):
    """Estimated total for `participants` paying `ticket` (default group ticket) on `day`; escorts enter free.

    Same rounding as the bookings created on approval (discount rounded to whole rupees).
    """
    prices = ticket_prices(museum, day)
    ticket = ticket or services.default_group_ticket_type(museum)
    row = next((p for p in prices if ticket and p["id"] == ticket.id), None)
    pct = services.group_discount_percent(museum, group_type) if discount_percent is None else discount_percent
    unit = row["price"] if row else Decimal(0)
    subtotal = unit * participants
    discount = (subtotal * Decimal(pct) / Decimal(100)).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
    weekly, reason = closed_info(museum, day)
    return {
        "date": day,
        "closed": closed_message(museum, day),  # message, or None when open
        "closed_weekly": weekly,
        "closed_reason": reason,
        "ticket_type": row and {"id": row["id"], "name": row["name"], "base_price": row["base_price"],
                                "price": row["price"], "rule": row["rule"]},
        "participants": participants,
        "unit_price": unit,
        "base_unit_price": row["base_price"] if row else Decimal(0),
        "price_rule": row["rule"] if row else None,
        "subtotal": subtotal,
        "discount_percent": pct,
        "discount": discount,
        "total": subtotal - discount,
        "ticket_types": prices,
    }
