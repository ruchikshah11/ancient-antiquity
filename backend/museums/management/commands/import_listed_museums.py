"""Import information-only museums (no tickets yet) from a JSON list collected from Wikipedia, Wikidata and
OpenStreetMap:

    python manage.py import_listed_museums path/to/to_import.json [--wiki]

Each row: {name, city, state, article?, qid?, lat?, lng?, year?, kind?, phone?, website?, osm?, source}.
Places are created without ticket types or slots, so they can't be booked until an admin adds them in the
place editor; `info_verified` stays off. Re-running skips places that already exist (same name + city).
--wiki copies the description and photo from each place's OWN Wikipedia article (never a name search).
"""
import json
import re
import time
from datetime import time as clock
from decimal import Decimal

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from museums import wikipedia
from museums.models import Category, City, Museum, State

CATEGORY_WORDS = [
    ("Art & Sculpture", ("art", "gallery", "painting", "sculpture", "kala")),
    ("Science & Technology", ("science", "technology", "planetarium", "railway", "rail", "aviation", "space", "computer", "automobile", "car")),
    ("Military", ("war ", "war,", " war", "battle", "military", "army", "navy", "naval", "air force", "regiment", "submarine",
                  "cavalry", "police", "fire service", "warship", "tank museum")),
    ("Natural History", ("natural history", "zoological", "botanical", "geology", "fossil", "shell", "marine", "aquarium", "bird")),
    ("Memorial", ("memorial", "smarak", "house", "bhavan", "ashram", "birthplace", "samadhi")),
    ("Tribal & Folk", ("tribal", "folk", "anthropolog", "ethnograph", "heritage village", "tribe")),
    ("Textiles & Crafts", ("textile", "craft", "handloom", "doll", "toy", "coin", "stamp", "philatel")),
    ("Archaeology", ("archaeolog", "excavat", "site museum")),
    ("Palace Museum", ("palace", "mahal")),
]


def category_for(name, kind):
    text = f"{name} {kind}".lower()
    for category, words in CATEGORY_WORDS:
        if any(w in text for w in words):
            return category
    return "History"


class Command(BaseCommand):
    help = "Import information-only museums (no tickets) from a collected JSON list"

    def add_arguments(self, parser):
        parser.add_argument("path")
        parser.add_argument("--wiki", action="store_true", help="Add description/photo from each place's own Wikipedia article")

    def handle(self, path, wiki=False, **opts):
        rows = json.load(open(path, encoding="utf-8"))
        states = {s.name.lower(): s for s in State.objects.all()}
        aliases = {"punjab": "punjab", "delhi": "delhi"}
        categories = {c.name: c for c in Category.objects.all()}
        existing = set(Museum.objects.values_list("name", "city__name"))
        created, skipped, no_state = [], 0, 0
        with transaction.atomic():
            for r in rows:
                state = states.get(r["state"].lower()) or states.get(aliases.get(r["state"].lower(), ""))
                if state is None:
                    state = next((s for k, s in states.items() if r["state"].lower() in k or k in r["state"].lower()), None)
                if state is None:
                    no_state += 1
                    continue
                city_name = (r.get("city") or "").strip() or state.name
                city_name = re.sub(r"\s+", " ", city_name)[:100]
                if (r["name"], city_name) in existing:
                    skipped += 1
                    continue
                city, _ = City.objects.get_or_create(name=city_name, state=state)
                category_name = category_for(r["name"], r.get("kind", ""))
                category = categories.get(category_name) or categories.get("History")
                source = (f"https://en.wikipedia.org/wiki/{r['article'].replace(' ', '_')}" if r.get("article")
                          else f"https://www.openstreetmap.org/{r['osm']}" if r.get("osm")
                          else f"https://www.wikidata.org/wiki/{r['qid']}" if r.get("qid") else "")
                where = city.name if city.name == state.name else f"{city.name}, {state.name}"
                museum = Museum.objects.create(
                    name=r["name"][:150], city=city, category=category, place_type=Museum.PlaceType.MUSEUM,
                    tagline=f"Museum in {where}"[:200],
                    description=(f"{r['name']} is a museum in {where}. Opening hours and entry fees are not listed here "
                                 f"yet; please contact the museum before you visit."),
                    address=where[:255],
                    latitude=Decimal(str(round(r["lat"], 6))) if r.get("lat") else None,
                    longitude=Decimal(str(round(r["lng"], 6))) if r.get("lng") else None,
                    # source_url credits the description; it is set only when Wikipedia text is copied (--wiki).
                    established_year=r.get("year"),
                    contact_phone=re.sub(r"[^\d+ ]", "", (r.get("phone") or "").split(";")[0])[:20],
                    # Not shown to visitors while there are no tickets (see MuseumDetail); placeholders only.
                    opening_time=clock(10, 0), closing_time=clock(17, 0),
                    info_verified=False,
                )
                existing.add((museum.name, city.name))
                created.append((museum, r))
        self.stdout.write(f"Created {len(created)} places; skipped {skipped} already present; {no_state} without a known state.")

        if wiki:
            done = 0
            for museum, r in created:
                if not r.get("article"):
                    continue
                try:
                    entry = wikipedia.fetch_museum(museum.name, museum.city.name, r["article"])
                except Exception as exc:  # network hiccup: leave the generic text
                    self.stderr.write(f"  {museum.name}: {exc}")
                    continue
                if entry and wikipedia.apply_to_museum(museum, entry, force=True):
                    done += 1
                time.sleep(0.2)
            self.stdout.write(f"Added Wikipedia descriptions/photos to {done} places.")
        if not created and not skipped:
            raise CommandError("Nothing imported: check the file's state names.")
