"""Coordinates and distances for places. Plain Python: a few hundred rows don't need PostGIS."""
import json
import math
from collections import defaultdict
from pathlib import Path

from museums.models import City, Museum

EARTH_RADIUS_KM = 6371.0088


def haversine_km(lat1, lng1, lat2, lng2):
    lat1, lng1, lat2, lng2 = map(math.radians, (float(lat1), float(lng1), float(lat2), float(lng2)))
    a = math.sin((lat2 - lat1) / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin((lng2 - lng1) / 2) ** 2
    return 2 * EARTH_RADIUS_KM * math.asin(min(1.0, math.sqrt(a)))


def sized_image(url, width=330):
    """Wikimedia thumbnails are stored at 1280px; markers and popups only need a small one."""
    if url and "wikimedia.org" in url:
        return url.replace("/1280px-", f"/{width}px-")
    return url or ""


def starting_price(museum):
    """Same rule as MuseumListSerializer: lowest paid active ticket, 0 if all free, None if none."""
    prices = [t.price for t in museum.ticket_types.all() if t.is_active]
    if not prices:
        return None
    paid = [p for p in prices if p > 0]
    return min(paid) if paid else 0


def _geocoded_cities():
    """{"City|State": (lat, lng)} from the fetch_coordinates cache (OpenStreetMap city geocodes), if present."""
    path = Path(__file__).resolve().parent.parent / "museums" / "data" / "coordinates_cache.json"
    try:
        cities = json.loads(path.read_text(encoding="utf-8")).get("cities", {})
    except (OSError, ValueError):
        return {}
    return {key: (c["lat"], c["lng"]) for key, c in cities.items() if c}


def city_centroids(city_ids=None):
    """Average position of the located places in each city, used for places without their own pin.
    Cities with no located place fall back to the city's geocoded centre (see fetch_coordinates)."""
    qs = Museum.objects.filter(latitude__isnull=False, longitude__isnull=False)
    if city_ids is not None:
        qs = qs.filter(city_id__in=city_ids)
    points = defaultdict(list)
    for city_id, lat, lng in qs.values_list("city_id", "latitude", "longitude"):
        points[city_id].append((float(lat), float(lng)))
    out = {cid: (sum(p[0] for p in pts) / len(pts), sum(p[1] for p in pts) / len(pts)) for cid, pts in points.items()}
    missing = Museum.objects.filter(latitude__isnull=True).exclude(city_id__in=list(out))
    if city_ids is not None:
        missing = missing.filter(city_id__in=city_ids)
    pending = dict(missing.values_list("city_id", "city__name").distinct())
    if pending:
        geocoded = _geocoded_cities()
        states = dict(City.objects.filter(pk__in=pending).values_list("pk", "state__name"))
        for cid, name in pending.items():
            centre = geocoded.get(f"{name}|{states.get(cid)}")
            if centre:
                out[cid] = centre
    return out


def coordinates(museum, centroids):
    """(lat, lng, approximate) or None. Approximate = city centre of other places in the same city."""
    if museum.latitude is not None and museum.longitude is not None:
        return float(museum.latitude), float(museum.longitude), False
    centre = centroids.get(museum.city_id)
    if centre:
        return centre[0], centre[1], True
    return None


def located_places(place_types=None):
    """Active places with a position, as compact dicts for the map."""
    qs = Museum.objects.filter(is_active=True).select_related("city__state").prefetch_related("ticket_types")
    if place_types:
        qs = qs.filter(place_type__in=place_types)
    centroids = city_centroids()
    rows = []
    for m in qs.order_by("name", "id"):
        pos = coordinates(m, centroids)
        if pos is None:
            continue
        price = starting_price(m)
        rows.append({
            "id": m.id,
            "slug": m.slug,
            "name": m.name,
            "place_type": m.place_type,
            "city": m.city.name,
            "state": m.city.state.name,
            "lat": round(pos[0], 6),
            "lng": round(pos[1], 6),
            "approximate": pos[2],
            "image_url": sized_image(m.image_url),
            "starting_price": None if price is None else str(price),
        })
    return rows
