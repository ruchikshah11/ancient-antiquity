"""CSV import for museums, used by `manage.py import_museums`, `seed_india` and the admin upload.

Required columns: name, city, state (code like MH or full name), category, operator
Optional columns: type (museum / fort / palace / monument), tagline, description, highlights, address, latitude, longitude, image_url,
    established_year, managed_by, opening_time, closing_time, closed_day (Monday..Sunday / none),
    price_indian, price_foreign, price_student, price_child, slot_capacity, featured (yes/no)

Anything left blank falls back to the defaults of the `operator` type below. Those defaults are
typical values, not official ones - confirm timings and prices with each museum.
"""
import csv
from datetime import time
from decimal import Decimal, InvalidOperation

from django.db import transaction

from .models import Category, City, Museum, State, TicketType, TimeSlot

WEEKDAYS = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]

TICKETS = [
    ("Indian Citizen (Adult)", "Indian nationals aged 12+"),
    ("Foreign National", "Includes OCI card holders where applicable"),
    ("Student", "Valid student ID required at entry"),
    ("Child (below 12)", "Accompanied by an adult"),
]

ASI = "Archaeological Survey of India"
# ASI admits children under 15 free at its monuments and site museums.
ASI_TICKETS = [
    ("Indian Citizen (Adult)", "Indian nationals aged 15+"),
    TICKETS[1],
    TICKETS[2],
    ("Child (below 15)", "Free entry under 15 (ASI rule), accompanied by an adult"),
]


def tickets_for(managed_by):
    """Visitor categories for a place; age bands depend on who runs it."""
    return ASI_TICKETS if managed_by == ASI else TICKETS

# operator: (managed_by, open, close, closed weekday or None, (indian, foreign, student, child))
OPERATORS = {
    "asi": ("Archaeological Survey of India", time(9), time(17), 4, (5, 5, 0, 0)),
    "central": ("Ministry of Culture, Govt. of India", time(10), time(17), 0, (20, 500, 10, 0)),
    "state": ("State Department of Archaeology & Museums", time(10), time(17), 0, (20, 200, 10, 0)),
    "ncsm": ("National Council of Science Museums", time(10), time(18), None, (70, 70, 50, 50)),
    "trust": ("Museum Trust / Society", time(10), time(17), 0, (50, 300, 25, 0)),
    "private": ("Private", time(10), time(18), None, (100, 500, 50, 50)),
    "palace": ("Royal Family Trust", time(9, 30), time(17), None, (150, 600, 75, 50)),
    "defence": ("Indian Armed Forces", time(10), time(17), 0, (20, 100, 10, 0)),
    "university": ("University", time(10), time(17), 6, (20, 100, 10, 0)),
    "railway": ("Indian Railways", time(10), time(17, 30), 0, (50, 50, 20, 10)),
    # Ticketed forts and monuments: open sunrise to sunset, all week unless a row says otherwise.
    # ASI admits children under 15 free; students pay the Indian rate.
    "asi_monument": ("Archaeological Survey of India", time(6), time(18), None, (35, 550, 35, 0)),
    "state_monument": ("State Department of Archaeology & Museums", time(8), time(17, 30), None, (100, 500, 25, 0)),
}

PLACE_TYPES = ("museum", "fort", "palace", "monument")
# Open-air sites move far more people per hour than galleries.
DEFAULT_CAPACITY = {"museum": 100, "palace": 150, "fort": 300, "monument": 300}


def build_slots(opening, closing):
    """Hourly entry slots; the first starts at opening, the last ends at closing."""
    slots, hour = [], opening.hour
    while hour + 1 <= closing.hour:
        start = time(hour, opening.minute if hour == opening.hour else 0)
        end = time(hour + 1) if hour + 1 < closing.hour else closing
        if start < end:
            slots.append((start, end))
        hour += 1
    return slots or [(opening, closing)]


def _time(value, default):
    value = (value or "").strip()
    if not value:
        return default
    h, _, m = value.partition(":")
    return time(int(h), int(m or 0))


def _price(value, default):
    value = (value or "").strip().replace("₹", "").replace(",", "")
    if not value:
        return Decimal(default)
    try:
        price = Decimal(value)
    except InvalidOperation:
        raise ValueError(f"invalid price '{value}'")
    if price < 0:
        raise ValueError("price cannot be negative")
    return price


def _closed_day(value, default):
    value = (value or "").strip().lower()
    if not value:
        return default
    if value in ("none", "open", "-", "no"):
        return None
    if value not in WEEKDAYS:
        raise ValueError(f"closed_day must be a weekday name or 'none', got '{value}'")
    return WEEKDAYS.index(value)


def _find_state(value, states):
    key = (value or "").strip().lower()
    state = states.get(key)
    if not state:
        raise ValueError(f"unknown state '{value}'")
    return state


def import_museums(file_obj, update=False):
    """Create museums (with ticket types and hourly slots) from CSV rows.

    Existing museums (same name + city) are skipped, or updated when update=True.
    Each row runs in its own transaction, so one bad row doesn't stop the rest.
    """
    states = {}
    for s in State.objects.all():
        states[s.code.lower()] = s
        states[s.name.lower()] = s

    reader = csv.DictReader(file_obj)
    missing = {"name", "city", "state", "category", "operator"} - set(reader.fieldnames or [])
    if missing:
        return {"created": 0, "updated": 0, "skipped": 0,
                "errors": [{"row": 1, "error": f"missing columns: {', '.join(sorted(missing))}"}]}

    created = updated = skipped = 0
    errors = []
    for line, row in enumerate(reader, start=2):
        row = {k.strip(): (v or "").strip() for k, v in row.items() if k}
        if not row.get("name"):
            continue
        try:
            with transaction.atomic():
                result = _import_row(row, states, update)
        except Exception as exc:  # report and continue with the next row
            errors.append({"row": line, "name": row.get("name"), "error": str(exc)})
            continue
        if result == "created":
            created += 1
        elif result == "updated":
            updated += 1
        else:
            skipped += 1
    return {"created": created, "updated": updated, "skipped": skipped, "errors": errors}


def _import_row(row, states, update):
    operator = row["operator"].lower()
    if operator not in OPERATORS:
        raise ValueError(f"operator must be one of {', '.join(OPERATORS)}")
    managed_by, opening, closing, closed, prices = OPERATORS[operator]

    state = _find_state(row["state"], states)
    city, _ = City.objects.get_or_create(name=row["city"], state=state)
    category, _ = Category.objects.get_or_create(name=row["category"])
    opening = _time(row.get("opening_time"), opening)
    closing = _time(row.get("closing_time"), closing)
    if closing <= opening:
        raise ValueError("closing_time must be after opening_time")

    place_type = (row.get("type") or ("palace" if row["category"] == "Palace Museum" else "museum")).lower()
    if place_type not in PLACE_TYPES:
        raise ValueError(f"type must be one of {', '.join(PLACE_TYPES)}")

    tagline = row.get("tagline", "")
    fields = dict(
        place_type=place_type,
        category=category,
        tagline=tagline,
        description=row.get("description") or f"{row['name']} in {city.name}, {state.name}. {tagline}".strip(),
        highlights=row.get("highlights", "").replace("|", "\n"),
        address=row.get("address") or f"{city.name}, {state.name}",
        latitude=row.get("latitude") or None,
        longitude=row.get("longitude") or None,
        image_url=row.get("image_url", ""),
        established_year=int(row["established_year"]) if row.get("established_year") else None,
        managed_by=row.get("managed_by") or managed_by,
        opening_time=opening,
        closing_time=closing,
        closed_weekday=_closed_day(row.get("closed_day"), closed),
        is_featured=row.get("featured", "").lower() in ("yes", "true", "1"),
    )
    prices = [
        _price(row.get(col), default)
        for col, default in zip(("price_indian", "price_foreign", "price_student", "price_child"), prices)
    ]
    capacity = int(row.get("slot_capacity") or DEFAULT_CAPACITY[place_type])

    museum = Museum.objects.filter(name=row["name"], city=city).first()
    if museum and not update:
        return "skipped"
    if museum:
        for k, v in fields.items():
            setattr(museum, k, v)
        museum.save()
        for (name, _), price in zip(tickets_for(museum.managed_by), prices):
            museum.ticket_types.filter(name=name).update(price=price)
        return "updated"

    museum = Museum.objects.create(name=row["name"], city=city, **fields)
    TicketType.objects.bulk_create([
        TicketType(museum=museum, name=name, description=desc, price=price, sort_order=i)
        for i, ((name, desc), price) in enumerate(zip(tickets_for(museum.managed_by), prices))
    ])
    TimeSlot.objects.bulk_create([
        TimeSlot(museum=museum, start_time=s, end_time=e, capacity=capacity)
        for s, e in build_slots(opening, closing)
    ])
    return "created"
