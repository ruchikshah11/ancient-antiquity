"""Give every place its exact map position (latitude / longitude).

    python manage.py fetch_coordinates            # apply data/coordinates_cache.json (no internet needed)
    python manage.py fetch_coordinates --fetch    # look up places missing from the cache, then apply
    python manage.py fetch_coordinates --refetch  # look up every place again
    python manage.py fetch_coordinates --force    # also overwrite coordinates an admin entered by hand

Sources, in order:
  1. The place's Wikipedia article (data/wiki_cache.json), via prop=coordinates, 50 titles per request.
     When the article is about the whole town (a town museum matched to the town's article), the town's
     coordinates are only kept as a last resort.
  2. OpenStreetMap Nominatim search "<name>, <city>, <state>, India". Usage policy: at most one request
     per second, a real User-Agent, and every answer cached so it is never asked twice.
  3. MANUAL below, for well-known places the sources can't resolve.

Every point must lie inside India's bounding box and within MAX_CITY_KM of the city's centre (Nominatim
geocode of "<city>, <state>, India", or the average of hand-entered places in that city). Anything else is
rejected and reported. Coordinates already on a place that this command did not write are treated as
entered by hand and kept unless --force.
"""
import json
import math
import re
import time
import urllib.parse
import urllib.request
from collections import Counter
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path

from django.core.management.base import BaseCommand

from museums import wikipedia
from museums.models import Museum

CACHE_PATH = Path(wikipedia.CACHE_PATH).with_name("coordinates_cache.json")
NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"
WIKIDATA_API = "https://www.wikidata.org/w/api.php"
NOMINATIM_INTERVAL = 1.1  # seconds between requests (policy: max 1 per second)
WIKI_BATCH = 50

INDIA_BOX = (6.0, 37.5, 68.0, 97.5)  # lat min, lat max, lng min, lng max
MAX_CITY_KM = 60

# Wikipedia coordinate types / Nominatim results that describe a whole settlement, not the place itself.
SETTLEMENT_TYPES = {"city", "town", "village", "hamlet", "suburb", "municipality", "county", "state", "region",
                    "district", "country", "adm1st", "adm2nd", "adm3rd", "administrative", "island", "isle"}
MUSEUM_WORDS = {"museum", "sangrahalaya", "gallery", "museums"}

# City geocodes that hit a namesake village far away. "City|State": (lat, lng) of the real town.
CITY_CENTRES = {
    "Bhangarh|Rajasthan": (27.096, 76.287),   # Nominatim: Bhangarh village in Hanumangarh district
    "Halebidu|Karnataka": (13.213, 75.994),   # Nominatim: Halebidu village in Mandya district
}

# Extra Nominatim searches (tried as written, after the place's own name) for places OpenStreetMap knows under
# another name, or that sit inside a better-known monument. "Name|City": [query, ...]
ALT_NAMES = {
    "Swatantrata Sangram Sangrahalaya|New Delhi": ["Red Fort, Delhi"],  # museum inside the Red Fort
    "Government Museum, Ajmer|Ajmer": ["Ajmer Museum"],  # OSM: Akbar's Fort & Museum
    "Government Museum, Bharatpur|Bharatpur": ["Bharatpur Museum"],
    "Thanjavur Art Gallery|Thanjavur": ["Thanjavur Palace"],  # gallery inside the Maratha palace
    "Kerala Folklore Museum|Kochi": ["Kerala Folklore Museum"],
    "INA Memorial Complex|Moirang": ["INA Museum, Moirang"],
    "Sri Krishna Museum|Kurukshetra": ["Shri Krishna Museum, Kurukshetra"],
    "Bhuri Singh Museum|Chamba": ["Bhuri Singh Museum, Chamba", "Chamba Museum"],
    "Nicholas Roerich Art Gallery|Naggar": ["Roerich Art Gallery, Naggar", "Roerich Estate, Naggar"],
    "Hall of Fame|Leh": ["Hall of Fame, Leh", "Hall of Fame Museum, Leh"],
    "Marine Museum|Kavaratti": ["Marine Museum, Kavaratti", "Marine Aquarium, Kavaratti"],
    "Jahaz Mahal, Mandu|Mandu": ["Jahaz Mahal, Mandav", "Jahaz Mahal, Dhar"],  # Wikipedia's article is Delhi's
}

# Hand-checked positions for places neither source resolves (or resolves wrongly). These always win over
# the fetched value. Only add places whose position is certain, e.g. a well-known monument's own map pin.
# "Name|City": (lat, lng)
MANUAL = {
    # ASI museum in the Fatehpur Sikri palace complex (Wikipedia's coordinates for the complex).
    "Archaeological Museum, Fatehpur Sikri|Fatehpur Sikri": (27.0945, 77.6679),
    # Jahaz Mahal in Mandu's Royal Enclave, between Munj and Kapur talao (Wikipedia's "Jahaz Mahal" is Delhi's).
    "Jahaz Mahal, Mandu|Mandu": (22.3566, 75.3925),
    # Opposite Raj Ghat; the article's own coordinates point ~50 km away near Baghpat but pass the 60 km check.
    "National Gandhi Museum|New Delhi": (28.6418, 77.2475),
}


# --- cache ------------------------------------------------------------------------------------------------

def load_cache():
    data = json.loads(CACHE_PATH.read_text(encoding="utf-8")) if CACHE_PATH.exists() else {}
    for section in ("cities", "places", "wikipedia", "nominatim", "applied"):
        data.setdefault(section, {})
    return data


def save_cache(cache):
    CACHE_PATH.write_text(json.dumps(cache, ensure_ascii=False, indent=1, sort_keys=True), encoding="utf-8")


# --- geometry and sanity ------------------------------------------------------------------------------------

def distance_km(lat1, lng1, lat2, lng2):
    lat1, lng1, lat2, lng2 = map(math.radians, (float(lat1), float(lng1), float(lat2), float(lng2)))
    a = math.sin((lat2 - lat1) / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin((lng2 - lng1) / 2) ** 2
    return 2 * 6371.0088 * math.asin(min(1.0, math.sqrt(a)))


def in_india(lat, lng):
    lat_min, lat_max, lng_min, lng_max = INDIA_BOX
    return lat_min <= lat <= lat_max and lng_min <= lng <= lng_max


def sanity_error(lat, lng, centre, max_km=MAX_CITY_KM):
    """Why (lat, lng) can't be this place's position, or None if it looks right.

    centre: (lat, lng) of the place's city, or None when unknown (then only the India box is checked).
    """
    try:
        lat, lng = float(lat), float(lng)
    except (TypeError, ValueError):
        return "not a number"
    if not in_india(lat, lng):
        return f"outside India ({lat:.4f}, {lng:.4f})"
    if centre is not None:
        km = distance_km(lat, lng, *centre)
        if km > max_km:
            return f"{km:.0f} km from the city centre ({lat:.4f}, {lng:.4f})"
    return None


def quantize(value):
    return Decimal(str(value)).quantize(Decimal("0.000001"), rounding=ROUND_HALF_UP)


# --- HTTP ---------------------------------------------------------------------------------------------------

_last_nominatim = [0.0]


def nominatim_get(query):
    """One Nominatim search, rate limited to one request per NOMINATIM_INTERVAL seconds."""
    wait = _last_nominatim[0] + NOMINATIM_INTERVAL - time.monotonic()
    if wait > 0:
        time.sleep(wait)
    params = {"format": "json", "q": query, "limit": 1, "countrycodes": "in"}
    req = urllib.request.Request(
        f"{NOMINATIM_URL}?{urllib.parse.urlencode(params)}",
        headers={"User-Agent": wikipedia.USER_AGENT, "Accept-Language": "en"},
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.loads(r.read())
    finally:
        _last_nominatim[0] = time.monotonic()


def nominatim(cache, query):
    """Cached Nominatim lookup: {"lat", "lng", "class", "type", "name"} or None."""
    if query in cache["nominatim"]:
        return cache["nominatim"][query]
    rows = nominatim_get(query)
    hit = None
    if rows:
        row = rows[0]
        hit = {"lat": float(row["lat"]), "lng": float(row["lon"]), "class": row.get("class", ""),
               "type": row.get("type", ""), "name": row.get("display_name", "")[:200]}
    cache["nominatim"][query] = hit
    return hit


def wikidata_get(params):
    """Wikidata API call with the same user agent and retry behaviour as museums.wikipedia._get."""
    params = {**params, "format": "json", "maxlag": "5"}
    req = urllib.request.Request(f"{WIKIDATA_API}?{urllib.parse.urlencode(params)}",
                                 headers={"User-Agent": wikipedia.USER_AGENT})
    for attempt in range(3):
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                return json.loads(r.read())
        except OSError:
            if attempt == 2:
                raise
            time.sleep(2 * (attempt + 1))
    return {}


def wikidata_coordinates(ids):
    """{Qid: (lat, lng)} from each item's P625 "coordinate location" (50 ids per request)."""
    out = {}
    ids = sorted(set(ids))
    for start in range(0, len(ids), WIKI_BATCH):
        data = wikidata_get({"action": "wbgetentities", "ids": "|".join(ids[start:start + WIKI_BATCH]),
                             "props": "claims"})
        for qid, entity in (data.get("entities") or {}).items():
            claims = sorted((entity.get("claims") or {}).get("P625", []), key=lambda c: c.get("rank") != "preferred")
            for claim in claims:
                value = (claim.get("mainsnak", {}).get("datavalue") or {}).get("value") or {}
                if "latitude" in value and value.get("globe", "").endswith("Q2"):  # on Earth
                    out[qid] = (value["latitude"], value["longitude"])
                    break
        time.sleep(0.2)
    return out


def wikipedia_coordinates(cache, titles):
    """Fill cache["wikipedia"][title] for titles not cached yet: {"lat", "lng", "type", "via"} or
    {"none": True} (50 titles per request). Articles without GeoData coordinates fall back to their
    Wikidata item's coordinate location (via = "wikidata")."""
    todo = sorted({t for t in titles if cache["wikipedia"].get(t) is None})
    missing = {}  # title -> Wikidata id, for articles without GeoData coordinates
    for start in range(0, len(todo), WIKI_BATCH):
        batch = todo[start:start + WIKI_BATCH]
        data = wikipedia._get({
            "action": "query", "prop": "coordinates|pageprops", "titles": "|".join(batch),
            "coprop": "type|dim", "colimit": "max", "ppprop": "wikibase_item", "redirects": "1",
        })
        query = data.get("query", {})
        # requested title -> final title (normalised and redirected)
        final = {t: t for t in batch}
        for step in ("normalized", "redirects"):
            moves = {m["from"]: m["to"] for m in query.get(step, [])}
            final = {t: moves.get(f, f) for t, f in final.items()}
        pages = {p["title"]: p for p in query.get("pages", [])}
        for title in batch:
            page = pages.get(final[title]) or {}
            coords = [c for c in page.get("coordinates", []) if c.get("primary", True)]
            if coords:
                cache["wikipedia"][title] = {"lat": coords[0]["lat"], "lng": coords[0]["lon"],
                                             "type": coords[0].get("type", ""), "via": "wikipedia"}
            else:
                cache["wikipedia"][title] = {"none": True}
                qid = (page.get("pageprops") or {}).get("wikibase_item")
                if qid:
                    missing[title] = qid
        time.sleep(0.2)  # be polite to the API
    if missing:
        found = wikidata_coordinates(missing.values())
        for title, qid in missing.items():
            if qid in found:
                lat, lng = found[qid]
                cache["wikipedia"][title] = {"lat": lat, "lng": lng, "type": "", "via": "wikidata", "qid": qid}
            else:
                cache["wikipedia"][title] = {"none": True, "qid": qid}


# --- per place --------------------------------------------------------------------------------------------------

def name_variants(name):
    """Search names, most specific first: as written; without '(…)' and '& Museum'; the part in brackets."""
    out = [name]
    plain = re.sub(r"\s*\(.*?\)", "", name)
    plain = re.sub(r"\s*&\s*(museum|ruins|hastkala academy)\b.*$", "", plain, flags=re.I).strip(" ,")
    if plain and plain not in out:
        out.append(plain)
    inner = re.search(r"\((.*?)\)", name)
    if inner and inner.group(1) not in out:
        out.append(inner.group(1))
    return out


def article_is_town(title, wiki_hit, museum_name, city_name):
    """The Wikipedia match describes the town (or a site much bigger than the place), not the place itself."""
    if wiki_hit and wiki_hit.get("type", "") in SETTLEMENT_TYPES:
        return True
    words = set(re.findall(r"[a-z]+", title.lower()))
    if words and words <= set(re.findall(r"[a-z]+", city_name.lower())):
        return True
    return bool(MUSEUM_WORDS & set(re.findall(r"[a-z]+", museum_name.lower()))) and not MUSEUM_WORDS & words


def is_settlement(hit):
    return hit["class"] in ("place", "boundary") and hit["type"] in SETTLEMENT_TYPES | {"administrative"}


def city_centre(cache, museum, hand_centroids):
    key = f"{museum.city.name}|{museum.city.state.name}"
    if key in CITY_CENTRES:
        return CITY_CENTRES[key]
    hit = cache["cities"].get(key)
    if hit:
        return hit["lat"], hit["lng"]
    return hand_centroids.get(museum.city_id)


def resolve(cache, museum, wiki_title, centre, fetch=True):
    """Find a sane position for one place. Returns (entry, rejected) where entry is {"lat","lng","source","ref"}
    or None and rejected lists "source: reason" strings."""
    rejected = []
    wiki_hit = cache["wikipedia"].get(wiki_title) if wiki_title else None
    if wiki_hit and "lat" not in wiki_hit:
        wiki_hit = None
    wiki_entry = None
    if wiki_hit:
        via = wiki_hit.get("via", "wikipedia")
        error = sanity_error(wiki_hit["lat"], wiki_hit["lng"], centre)
        if error:
            rejected.append(f"{via} '{wiki_title}': {error}")
        else:
            wiki_entry = {"lat": wiki_hit["lat"], "lng": wiki_hit["lng"], "source": via, "ref": wiki_title}
    elif wiki_title:
        rejected.append(f"wikipedia '{wiki_title}': no coordinates")
    town_level = bool(wiki_entry) and article_is_town(wiki_title, wiki_hit, museum.name, museum.city.name)
    if wiki_entry and not town_level:
        return wiki_entry, rejected

    queries = [f"{v}, {museum.city.name}, {museum.city.state.name}, India" for v in name_variants(museum.name)]
    queries += ALT_NAMES.get(wikipedia.cache_key(museum.name, museum.city.name), [])
    for query in queries:
        if query not in cache["nominatim"] and not fetch:
            continue
        hit = nominatim(cache, query)
        if not hit:
            continue
        if is_settlement(hit):
            rejected.append(f"nominatim '{query}': matched the {hit['type']} {hit['name'][:60]!r}, not the place")
            continue
        error = sanity_error(hit["lat"], hit["lng"], centre)
        if error:
            rejected.append(f"nominatim '{query}': {error}")
            continue
        return {"lat": hit["lat"], "lng": hit["lng"], "source": "nominatim", "ref": query}, rejected

    if wiki_entry:  # town-level article: better than nothing, flagged in the report
        return {**wiki_entry, "source": f"{wiki_entry['source']}-town"}, rejected
    return None, rejected


# --- command ------------------------------------------------------------------------------------------------------

class Command(BaseCommand):
    help = "Set exact latitude/longitude for every place from Wikipedia, OpenStreetMap Nominatim and a manual list"

    def add_arguments(self, parser):
        parser.add_argument("--fetch", action="store_true", help="Look up places not yet in the cache")
        parser.add_argument("--refetch", action="store_true", help="Look up every place again")
        parser.add_argument("--force", action="store_true", help="Overwrite coordinates entered by hand too")

    def handle(self, fetch=False, refetch=False, force=False, **opts):
        cache = load_cache()
        wiki = wikipedia.load_cache()
        museums = list(Museum.objects.select_related("city__state").order_by("pk"))
        keys = {m.pk: wikipedia.cache_key(m.name, m.city.name) for m in museums}
        hand = {m.pk for m in museums if m.latitude is not None and m.longitude is not None
                and not self._ours(cache, keys[m.pk], m)}
        hand_centroids = self._centroids([m for m in museums if m.pk in hand])

        if fetch or refetch:
            self._fetch(cache, wiki, museums, keys, hand_centroids, refetch)

        sources, failures, kept, changed = Counter(), [], 0, 0
        for m in museums:
            key = keys[m.pk]
            if m.pk in hand and not force:
                kept += 1
                sources["hand-entered (kept)"] += 1
                continue
            entry = None
            if key in MANUAL:
                entry = {"lat": MANUAL[key][0], "lng": MANUAL[key][1], "source": "manual"}
            else:
                cached = cache["places"].get(key) or {}
                if "lat" in cached:
                    error = sanity_error(cached["lat"], cached["lng"], city_centre(cache, m, hand_centroids))
                    if error:
                        cached = {"failed": [f"cached position: {error}"]}
                    else:
                        entry = cached
                if entry is None:
                    failures.append((m, cached.get("failed") or ["not looked up yet (run with --fetch)"]))
                    continue
            sources[entry["source"]] += 1
            lat, lng = quantize(entry["lat"]), quantize(entry["lng"])
            if (m.latitude, m.longitude) != (lat, lng):
                Museum.objects.filter(pk=m.pk).update(latitude=lat, longitude=lng)
                changed += 1
            cache["applied"][key] = [str(lat), str(lng)]  # written by this command, so later runs may update it
        save_cache(cache)

        self.stdout.write("Positions by source:")
        for source, n in sources.most_common():
            self.stdout.write(f"  {source}: {n}")
        if failures:
            self.stdout.write(self.style.WARNING(f"{len(failures)} place(s) without an exact position:"))
            for m, reasons in failures:
                self.stdout.write(f"  {m.name} ({m.city.name}): {'; '.join(reasons)}")
        exact = Museum.objects.filter(latitude__isnull=False, longitude__isnull=False).count()
        self.stdout.write(self.style.SUCCESS(
            f"Updated {changed} place(s); {kept} hand-entered kept. {exact}/{len(museums)} places have exact coordinates."
        ))

    @staticmethod
    def _ours(cache, key, museum):
        """The place's coordinates are the ones this command wrote (cache or MANUAL), so they may be updated."""
        current = (museum.latitude, museum.longitude)
        applied = cache["applied"].get(key)
        if applied and current == (Decimal(applied[0]), Decimal(applied[1])):
            return True
        if key in MANUAL and current == (quantize(MANUAL[key][0]), quantize(MANUAL[key][1])):
            return True
        entry = cache["places"].get(key) or {}
        return "lat" in entry and current == (quantize(entry["lat"]), quantize(entry["lng"]))

    @staticmethod
    def _centroids(museums):
        points = {}
        for m in museums:
            points.setdefault(m.city_id, []).append((float(m.latitude), float(m.longitude)))
        return {cid: (sum(p[0] for p in pts) / len(pts), sum(p[1] for p in pts) / len(pts)) for cid, pts in points.items()}

    def _fetch(self, cache, wiki, museums, keys, hand_centroids, refetch):
        todo = [m for m in museums if refetch or "lat" not in (cache["places"].get(keys[m.pk]) or {})]
        if refetch:
            cache["wikipedia"], cache["nominatim"] = {}, {}
        self.stdout.write(f"Looking up {len(todo)} places…")

        # City centres for the distance check (one Nominatim request per city, cached).
        for m in todo:
            city_key = f"{m.city.name}|{m.city.state.name}"
            if city_key in cache["cities"] and not refetch:
                continue
            try:
                hit = nominatim(cache, f"{m.city.name}, {m.city.state.name}, India")
            except OSError as exc:
                self.stderr.write(f"  city {city_key}: {exc}")
                continue
            ok = hit and in_india(hit["lat"], hit["lng"])
            cache["cities"][city_key] = {"lat": hit["lat"], "lng": hit["lng"]} if ok else None
        save_cache(cache)

        titles = {m.pk: (wiki.get(keys[m.pk]) or {}).get("title") for m in todo}
        try:
            wikipedia_coordinates(cache, [t for t in titles.values() if t])
        except OSError as exc:
            self.stderr.write(f"  Wikipedia: {exc}")
        save_cache(cache)

        for n, m in enumerate(todo, 1):
            centre = city_centre(cache, m, hand_centroids)
            try:
                entry, rejected = resolve(cache, m, titles[m.pk], centre)
            except OSError as exc:  # network hiccup: leave uncached, retry next run
                self.stderr.write(f"  {m.name}: {exc}")
                continue
            if centre is None:
                rejected.append("city centre unknown: only the India box was checked")
            cache["places"][keys[m.pk]] = {**entry, "notes": rejected} if entry else {"failed": rejected or ["no match"]}
            where = f"{entry['source']} ({entry['lat']:.4f}, {entry['lng']:.4f})" if entry else "NOT FOUND"
            self.stdout.write(f"  [{n}/{len(todo)}] {m.name}, {m.city.name}: {where}")
            for reason in rejected:
                self.stdout.write(f"      rejected {reason}")
            if n % 20 == 0:
                save_cache(cache)
        save_cache(cache)
