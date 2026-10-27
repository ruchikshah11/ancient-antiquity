"""Tools the AI assistant may call. Every fact it gives about places, prices, timings and bookings comes from here.

Each tool is a JSON-schema definition (sent to Claude, in a fixed order so the prompt cache stays valid) plus
an executor `fn(ctx, **input) -> dict`. Executors never raise for bad input: they return {"error": ...} so the
model can recover. `ctx` carries the request user and collects `links` (buttons shown under the answer).
"""
import datetime
import logging
from urllib.parse import urlencode

from django.apps import apps
from django.conf import settings
from django.db.models import Min, Q
from django.utils import timezone
from django.utils.dateparse import parse_date
from museums.groups import groups_open

logger = logging.getLogger(__name__)

WEEKDAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
MAX_SEARCH_RESULTS = 8
DESCRIPTION_CHARS = 700


class ToolContext:
    """Per-request state shared by the tool executors."""

    def __init__(self, user=None):
        self.user = user if user is not None and getattr(user, "is_authenticated", False) else None
        self.links = []

    def add_link(self, label, url):
        if not any(link["url"] == url for link in self.links):
            self.links.append({"label": label[:80], "url": url})


# ------------------------------------------------------------------ helpers

def _today():
    return timezone.localdate()


def _place_url(museum, date=None, slot=None):
    url = f"/museums/{museum.slug}"
    params = []
    if date:
        params.append(f"date={date.isoformat()}")
    if slot:
        params.append(f"slot={slot}")
    return url + ("?" + "&".join(params) if params else "")


def _hhmm(t):
    return t.strftime("%H:%M") if t else None


def _money(value):
    return float(value) if value is not None else None


def _parse_day(value, default=None):
    if not value:
        return default
    day = parse_date(str(value)) if not isinstance(value, datetime.date) else value
    return day or default


def _weekday_index(value):
    if value is None or value == "":
        return None
    if isinstance(value, int):
        return value if 0 <= value <= 6 else None
    text = str(value).strip().lower()
    if text.isdigit():
        n = int(text)
        return n if 0 <= n <= 6 else None
    for i, name in enumerate(WEEKDAYS):
        if name.lower().startswith(text[:3]):
            return i
    return None


def _active_places():
    from museums.models import Museum

    return Museum.objects.filter(is_active=True).select_related("city__state", "category")


def _get_place(slug):
    if not slug:
        return None
    return _active_places().filter(slug=str(slug).strip().lower()).first()


def _summary(museum):
    return {
        "slug": museum.slug,
        "name": museum.name,
        "type": museum.place_type,
        "city": museum.city.name,
        "state": museum.city.state.name,
        "opening_time": _hhmm(museum.opening_time),
        "closing_time": _hhmm(museum.closing_time),
        "closed_weekday": WEEKDAYS[museum.closed_weekday] if museum.closed_weekday is not None else None,
        "url": _place_url(museum),
    }


# ------------------------------------------------------------------ executors

def search_places(ctx, query="", state="", type="", city="", open_on_weekday=None, **_):
    from museums.models import Museum

    qs = _active_places()
    query, state, city = (query or "").strip(), (state or "").strip(), (city or "").strip()
    if query:
        words = [w for w in query.split() if len(w) > 1][:6] or [query]
        for word in words:
            qs = qs.filter(
                Q(name__icontains=word) | Q(city__name__icontains=word) | Q(city__state__name__icontains=word)
                | Q(tagline__icontains=word) | Q(category__name__icontains=word)
            )
    if state:
        qs = qs.filter(Q(city__state__name__icontains=state) | Q(city__state__code__iexact=state))
    if city:
        qs = qs.filter(city__name__icontains=city)
    if type:
        if type not in Museum.PlaceType.values:
            return {"error": f"type must be one of {', '.join(Museum.PlaceType.values)}"}
        qs = qs.filter(place_type=type)
    weekday = _weekday_index(open_on_weekday)
    if weekday is not None:
        qs = qs.exclude(closed_weekday=weekday)
    total = qs.count()
    rows = list(
        qs.annotate(from_price=Min("ticket_types__price", filter=Q(ticket_types__is_active=True)))
        .order_by("-is_featured", "name")[:MAX_SEARCH_RESULTS]
    )
    results = []
    for m in rows:
        item = _summary(m)
        item["from_price_inr"] = _money(m.from_price)
        item["tagline"] = m.tagline
        results.append(item)
    if 0 < len(rows) <= 3:
        for m in rows:
            ctx.add_link(m.name, _place_url(m))
    elif rows:
        params = []
        if query:
            params.append(urlencode({"search": query}))
        ctx.add_link("Browse all matches", "/museums" + ("?" + "&".join(params) if params else ""))
    return {"total_matches": total, "results": results,
            "note": "Weekly closed day only; check get_place for calendar closures on a specific date."}


def get_place(ctx, slug="", date=None, **_):
    from bookings.services import prices_for
    from museums.models import PlaceClosure

    museum = _get_place(slug)
    if not museum:
        return {"error": f"No active place with slug '{slug}'. Use search_places to find the slug."}
    today = _today()
    day = _parse_day(date, today)
    closures = [
        {
            "from": c.start_date.isoformat(), "to": c.end_date.isoformat(), "reason": c.reason,
            "whole_day": c.all_day,
            "slots": [f"{_hhmm(s.start_time)}-{_hhmm(s.end_time)}" for s in c.slots.all()] if not c.all_day else [],
        }
        for c in PlaceClosure.covering(museum, today, today + datetime.timedelta(days=30)).prefetch_related("slots")
    ]
    prices = [
        {"ticket": p["name"], "price_inr": _money(p["price"]), "base_price_inr": _money(p["base_price"]),
         "price_rule": p["rule"]}
        for p in prices_for(museum, day)
    ]
    facilities = museum.facilities or {}
    data = _summary(museum)
    data.update({
        "tagline": museum.tagline,
        "description": (museum.description or "")[:DESCRIPTION_CHARS],
        "highlights": [h.strip() for h in (museum.highlights or "").splitlines() if h.strip()][:8],
        "address": museum.address,
        "managed_by": museum.managed_by,
        "category": museum.category.name if museum.category_id else None,
        "info_verified": museum.info_verified,
        "slots": [f"{_hhmm(s.start_time)}-{_hhmm(s.end_time)}" for s in museum.slots.filter(is_active=True)],
        "prices_date": day.isoformat(),
        "prices": prices,
        "closures_next_30_days": closures,
        "facilities": {k: v for k, v in facilities.items() if v not in ("", None, False)},
        "groups_accepted": groups_open(museum, "instant"),
        "group_requests_accepted": groups_open(museum, "request"),
        "group_discount_percent": museum.group_discount_percent if museum.allow_groups else None,
        "school_discount_percent": museum.school_discount_percent if museum.allow_groups else None,
    })
    ctx.add_link(f"Book {museum.name}", _place_url(museum, day if date else None))
    return data


def check_availability(ctx, slug="", date="", **_):
    from bookings.services import booked_visitors_by_slot, prices_for
    from museums.views import crowd_level

    museum = _get_place(slug)
    if not museum:
        return {"error": f"No active place with slug '{slug}'. Use search_places to find the slug."}
    day = _parse_day(date)
    if not day:
        return {"error": "Pass date as YYYY-MM-DD."}
    today = _today()
    last_day = today + datetime.timedelta(days=settings.BOOKING_WINDOW_DAYS)
    if not today <= day <= last_day:
        return {"date": day.isoformat(), "bookable": False,
                "reason": f"Online booking is open from today up to {settings.BOOKING_WINDOW_DAYS} days ahead "
                          f"({today.isoformat()} to {last_day.isoformat()})."}
    closure = museum.closure_on(day)
    weekly_closed = museum.is_closed_on(day)
    if weekly_closed or closure["closed"]:
        reason = closure["reason"] if closure["closed"] else f"Closed every {WEEKDAYS[museum.closed_weekday]}"
        ctx.add_link(f"{museum.name}: other dates", _place_url(museum))
        return {"date": day.isoformat(), "weekday": WEEKDAYS[day.weekday()], "closed": True, "reason": reason}
    booked = booked_visitors_by_slot(museum, day)
    now = timezone.localtime().time()
    slots = []
    for slot in museum.slots.filter(is_active=True):
        taken = booked.get(slot.id, 0)
        slot_closed = closure["slots"].get(slot.id)
        started = day == today and slot.start_time <= now
        slots.append({
            "slot": f"{_hhmm(slot.start_time)}-{_hhmm(slot.end_time)}",
            "slot_id": slot.id,
            "remaining": max(slot.capacity - taken, 0),
            "crowd": crowd_level(taken, slot.capacity),
            "bookable": not slot_closed and not started and taken < slot.capacity,
            "closed_reason": slot_closed,
        })
    best = next((s for s in sorted(slots, key=lambda s: -s["remaining"]) if s["bookable"]), None)
    ctx.add_link(f"Book {museum.name} on {day:%d %b}", _place_url(museum, day, best and best["slot_id"]))
    return {
        "place": museum.name, "date": day.isoformat(), "weekday": WEEKDAYS[day.weekday()], "closed": False,
        "slots": slots,
        "prices": [{"ticket": p["name"], "price_inr": _money(p["price"])} for p in prices_for(museum, day)],
    }


def _event_model():
    try:
        return apps.get_model("events", "Event")
    except (LookupError, ImportError):
        return None


def list_events(ctx, slug="", city="", date_from="", date_to="", **_):
    Event = _event_model()
    if Event is None:
        return {"events": [], "note": "Event listings are not available on the site yet."}
    try:
        fields = {f.name for f in Event._meta.get_fields()}
        date_field = next((f for f in ("start_date", "date", "starts_at", "start", "event_date") if f in fields), None)
        title_field = next((f for f in ("title", "name") if f in fields), None)
        qs = Event.objects.all()
        if "is_active" in fields:
            qs = qs.filter(is_active=True)
        if "is_published" in fields:
            qs = qs.filter(is_published=True)
        if slug and "museum" in fields:
            qs = qs.filter(museum__slug=slug)
        elif city and "museum" in fields:
            qs = qs.filter(museum__city__name__icontains=city)
        if date_field:
            start = _parse_day(date_from, _today())
            end = _parse_day(date_to, start + datetime.timedelta(days=60))
            lookup = f"{date_field}__date" if Event._meta.get_field(date_field).get_internal_type() == "DateTimeField" else date_field
            qs = qs.filter(**{f"{lookup}__gte": start, f"{lookup}__lte": end}).order_by(date_field)
        events = []
        for e in qs[:10]:
            item = {"title": getattr(e, title_field, str(e)) if title_field else str(e)}
            if date_field:
                item["when"] = str(getattr(e, date_field))
            museum = getattr(e, "museum", None) if "museum" in fields else None
            if museum is not None:
                item["place"] = museum.name
                item["place_slug"] = museum.slug
            for extra in ("description", "price", "end_date", "ends_at", "venue"):
                if extra in fields and getattr(e, extra, None) not in (None, ""):
                    value = getattr(e, extra)
                    item[extra] = str(value)[:300]
            if "slug" in fields and getattr(e, "slug", ""):
                item["url"] = f"/events/{e.slug}"
            events.append(item)
        return {"events": events}
    except Exception:  # the events app is evolving; never let it break the chat
        logger.exception("list_events failed")
        return {"events": [], "note": "Event listings could not be loaded right now."}


def my_bookings(ctx, **_):
    from bookings.models import Booking

    if ctx.user is None:
        ctx.add_link("Sign in", "/login")
        return {"error": "not_signed_in", "message": "The visitor is not signed in; ask them to sign in to see bookings."}
    rows = (
        Booking.objects.filter(user=ctx.user).select_related("museum", "slot").order_by("-created_at")[:10]
    )
    bookings = []
    for b in rows:
        bookings.append({
            "reference": b.reference, "place": b.museum.name, "place_slug": b.museum.slug,
            "visit_date": b.visit_date.isoformat(),
            "slot": f"{_hhmm(b.slot.start_time)}-{_hhmm(b.slot.end_time)}",
            "status": b.status, "visitors": b.total_visitors, "amount_inr": _money(b.total_amount),
            "can_cancel": b.can_cancel, "refund_if_cancelled_now_inr": _money(b.refundable_amount),
        })
    ctx.add_link("My bookings", "/my-bookings")
    for b in rows[:3]:
        if b.status in (Booking.Status.CONFIRMED, Booking.Status.CHECKED_IN):
            ctx.add_link(f"Ticket {b.reference}", f"/tickets/{b.reference}")
        elif b.status == Booking.Status.PENDING and not b.is_hold_expired:
            ctx.add_link(f"Pay for {b.reference}", f"/checkout/{b.reference}")
    return {"bookings": bookings}


POLICY_TOPICS = ("refund", "cancellation", "groups", "children", "combo_passes", "payment", "booking_window")


def get_policy(ctx, topic="", **_):
    topic = (topic or "").strip().lower()
    hours = settings.REFUND_FULL_BEFORE_HOURS
    if topic in ("refund", "cancellation"):
        ctx.add_link("Refund policy", "/refund-policy")
        return {"topic": topic, "policy": (
            f"Visitors can cancel online from My bookings until the visit date. A paid online booking cancelled at "
            f"least {hours} hours before the slot starts gets a full refund to the original payment method; "
            f"cancellations closer than {hours} hours to the slot get no refund. Tickets paid in cash at a ticket "
            f"counter are refunded at the counter, not online. Unpaid bookings hold seats for "
            f"{settings.BOOKING_HOLD_MINUTES} minutes and then expire automatically at no cost."
        )}
    if topic == "groups":
        return {"topic": topic, "policy": (
            f"Groups of {settings.GROUP_MIN_SIZE}-{settings.GROUP_MAX_SIZE} paying people (schools, colleges, tour "
            f"operators, companies, NGOs) can book a group ticket on the place page when the place accepts groups. "
            f"Schools and colleges get the place's school discount and one free escort (teacher) per "
            f"{settings.GROUP_ESCORTS_PER} students; other groups get the group discount. Groups can use at most "
            f"{int(settings.GROUP_SLOT_SHARE * 100)}% of a slot. Larger groups or special arrangements: send a group "
            f"request from the place page (/group-request/<place slug>)."
        )}
    if topic == "children":
        return {"topic": topic, "policy": (
            "At monuments and site museums run by the Archaeological Survey of India (ASI), children below 15 "
            "years enter free and must be accompanied by an adult; they still need a (free) ticket in the booking "
            "so they are counted at the gate. Other places set their own child prices: check get_place for the "
            "ticket types."
        )}
    if topic == "combo_passes":
        try:
            ComboPass = apps.get_model("passes", "ComboPass")
            passes = [
                {"name": p.name, "slug": p.slug, "validity_days": p.validity_days,
                 "prices_inr": {k: _money(v) for k, v in p.prices.items()},
                 "places": [m.name for m in p.ordered_sites()][:8], "url": f"/passes/{p.slug}"}
                for p in ComboPass.objects.filter(is_active=True)[:8]
            ]
        except LookupError:
            passes = []
        ctx.add_link("Combo passes", "/passes")
        return {"topic": topic, "policy": (
            "A combo pass covers several places for one price. All places must be visited within the pass's validity "
            "(counted from the first visit date). Buy it on the Passes page."
        ), "passes": passes}
    if topic == "payment":
        return {"topic": topic, "policy": (
            f"Online bookings are paid by UPI, card or net banking on the checkout page right after choosing tickets. "
            f"Seats are held for {settings.BOOKING_HOLD_MINUTES} minutes while paying. The e-ticket with a QR code "
            f"is emailed and shown under My bookings once paid."
        )}
    if topic == "booking_window":
        return {"topic": topic, "policy": (
            f"Tickets can be booked online for today up to {settings.BOOKING_WINDOW_DAYS} days ahead, at most "
            f"{settings.MAX_TICKETS_PER_BOOKING} tickets per booking. A slot can't be booked online once it has started."
        )}
    return {"error": f"Unknown topic. Use one of: {', '.join(POLICY_TOPICS)}"}


# ------------------------------------------------------------------ definitions (order is fixed: prompt cache)

TOOL_DEFINITIONS = [
    {
        "name": "search_places",
        "description": (
            "Search the bookable heritage places (museums, forts, palaces, monuments) in India. Returns slug, "
            "city, state, opening hours, weekly closed day and the lowest ticket price. Use it to find a place's "
            "slug before calling get_place or check_availability."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Words from the name, city, state or category, e.g. 'Taj Mahal'"},
                "state": {"type": "string", "description": "State or union territory name, e.g. 'Rajasthan'"},
                "city": {"type": "string", "description": "City name, e.g. 'Delhi'"},
                "type": {"type": "string", "enum": ["museum", "fort", "palace", "monument"]},
                "open_on_weekday": {"type": "string", "description": "Only places not closed weekly on this day, e.g. 'Monday'"},
            },
            "additionalProperties": False,
        },
    },
    {
        "name": "get_place",
        "description": (
            "Full details of one place: description, timings, weekly closed day, calendar closures in the next 30 "
            "days, ticket prices for a date (seasonal pricing applied), facilities (accessibility, photography, "
            "best time to visit, nearest metro/station) and group discounts."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "slug": {"type": "string", "description": "Place slug from search_places"},
                "date": {"type": "string", "description": "YYYY-MM-DD for prices; defaults to today"},
            },
            "required": ["slug"],
            "additionalProperties": False,
        },
    },
    {
        "name": "check_availability",
        "description": (
            "Entry slots for a place on a date with remaining tickets and crowd level (quiet/moderate/busy/full), "
            "or why the place is closed that day."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "slug": {"type": "string"},
                "date": {"type": "string", "description": "YYYY-MM-DD"},
            },
            "required": ["slug", "date"],
            "additionalProperties": False,
        },
    },
    {
        "name": "list_events",
        "description": "Upcoming events (exhibitions, light shows, festivals) at a place or in a city between two dates.",
        "input_schema": {
            "type": "object",
            "properties": {
                "slug": {"type": "string", "description": "Place slug"},
                "city": {"type": "string"},
                "date_from": {"type": "string", "description": "YYYY-MM-DD, default today"},
                "date_to": {"type": "string", "description": "YYYY-MM-DD, default 60 days later"},
            },
            "additionalProperties": False,
        },
    },
    {
        "name": "my_bookings",
        "description": (
            "The signed-in visitor's own recent bookings (reference, place, date, status, refund if cancelled now). "
            "Returns not_signed_in for guests."
        ),
        "input_schema": {"type": "object", "properties": {}, "additionalProperties": False},
    },
    {
        "name": "get_policy",
        "description": "Site policies: refund, cancellation, groups, children (ASI under-15 rule), combo_passes, payment, booking_window.",
        "input_schema": {
            "type": "object",
            "properties": {"topic": {"type": "string", "enum": list(POLICY_TOPICS)}},
            "required": ["topic"],
            "additionalProperties": False,
        },
    },
]

EXECUTORS = {
    "search_places": search_places,
    "get_place": get_place,
    "check_availability": check_availability,
    "list_events": list_events,
    "my_bookings": my_bookings,
    "get_policy": get_policy,
}


def run_tool(ctx, name, tool_input):
    """Execute one tool call. Returns (result_dict, is_error)."""
    fn = EXECUTORS.get(name)
    if fn is None:
        return {"error": f"Unknown tool {name}"}, True
    if not isinstance(tool_input, dict):
        tool_input = {}
    try:
        result = fn(ctx, **{str(k): v for k, v in tool_input.items()})
    except Exception:
        logger.exception("Assistant tool %s failed", name)
        return {"error": "The tool failed; tell the visitor you could not look this up right now."}, True
    return result, "error" in result and len(result) <= 2
