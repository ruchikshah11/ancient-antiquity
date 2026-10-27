"""Photos from Google Maps (Places API, new) for places that have no free (Wikimedia) photo.

Setup: Google Cloud Console -> enable "Places API (New)" -> create an API key restricted to that API (and to the
server's IP) -> GOOGLE_MAPS_API_KEY=... in backend/.env -> python manage.py find_google_places.

Google's terms allow storing the place ID only, so photos are never downloaded or stored: the site keeps the place
ID (Museum.google_place_id) and asks Google for the photo when it is shown, caching the answer for a few hours
(GOOGLE_PHOTO_CACHE_HOURS) to keep the cost down. Each photo must show its author ("Photo: <name>, Google Maps").
"""
import json
import math
import re
import urllib.error
import urllib.parse
import urllib.request

from django.conf import settings
from django.core.cache import cache

API = "https://places.googleapis.com/v1"
MAX_PHOTOS = 10
GENERIC = {"museum", "museums", "the", "of", "and", "gallery", "art", "government", "state", "district", "national",
           "regional", "memorial", "science", "centre", "center", "house", "india", "indian", "new", "hall", "park",
           "sangrahalaya", "heritage", "historical", "archaeological", "archeological", "site", "cultural", "city"}


def enabled():
    return bool(getattr(settings, "GOOGLE_MAPS_API_KEY", ""))


def _ttl():
    return int(getattr(settings, "GOOGLE_PHOTO_CACHE_HOURS", 12)) * 3600


def _call(path, *, body=None, fields=None, params=None):
    url = f"{API}/{path}"
    if params:
        url += "?" + urllib.parse.urlencode(params)
    headers = {"X-Goog-Api-Key": settings.GOOGLE_MAPS_API_KEY}
    if fields:
        headers["X-Goog-FieldMask"] = fields
    data = None
    if body is not None:
        data = json.dumps(body).encode()
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, headers=headers)
    with urllib.request.urlopen(req, timeout=20) as r:
        return json.loads(r.read())


def _words(text):
    return set(re.findall(r"[a-z0-9]+", (text or "").lower()))


def _km(lat1, lng1, lat2, lng2):
    p = math.pi / 180
    a = 0.5 - math.cos((lat2 - lat1) * p) / 2 + math.cos(lat1 * p) * math.cos(lat2 * p) * (1 - math.cos((lng2 - lng1) * p)) / 2
    return 12742 * math.asin(math.sqrt(a))


def find_place(museum):
    """Best Google match for a place, or None. Only accepted when the name matches and (with coordinates) it is
    within 15 km, so a different museum in the same city is not picked up."""
    city = museum.city.name
    state = museum.city.state.name
    body = {"textQuery": f"{museum.name}, {city}, {state}, India", "regionCode": "IN", "languageCode": "en",
            "pageSize": 5}
    lat, lng = museum.latitude, museum.longitude
    if lat is not None and lng is not None:
        body["locationBias"] = {"circle": {"center": {"latitude": float(lat), "longitude": float(lng)}, "radius": 15000.0}}
    data = _call("places:searchText", body=body,
                 fields="places.id,places.displayName,places.formattedAddress,places.location,places.photos.name")
    own = {w for w in _words(museum.name) if len(w) > 2} - GENERIC
    for p in data.get("places", []):
        if not p.get("photos"):
            continue
        name = (p.get("displayName") or {}).get("text", "")
        words = _words(name)
        if own:
            if len(own & words) < min(2, len(own)):
                continue
        elif not (_words(museum.name) - {"the", "of", "and"}) <= words | _words(city):
            continue  # generic name ("Government Museum"): every word must match
        loc = p.get("location") or {}
        if lat is not None and lng is not None and loc:
            if _km(float(lat), float(lng), loc.get("latitude", 0), loc.get("longitude", 0)) > 15:
                continue
        elif city.lower() not in (p.get("formattedAddress") or "").lower():
            continue
        return {"id": p["id"], "name": name}
    return None


def photos(place_id):
    """[{name, author, author_uri}] for a place (cached)."""
    key = f"gplace:{place_id}"
    hit = cache.get(key)
    if hit is not None:
        return hit
    try:
        data = _call(f"places/{place_id}", fields="photos")
    except (urllib.error.URLError, OSError, ValueError):
        return []
    out = []
    for ph in (data.get("photos") or [])[:MAX_PHOTOS]:
        authors = ph.get("authorAttributions") or [{}]
        out.append({"name": ph["name"], "author": authors[0].get("displayName", ""), "author_uri": authors[0].get("uri", "")})
    cache.set(key, out, _ttl())
    return out


def photo_uri(place_id, index, width=1280):
    """Short-lived image URL on Google's servers for photo `index` of a place (cached), or None."""
    key = f"gphoto:{place_id}:{index}:{width}"
    hit = cache.get(key)
    if hit:
        return hit
    items = photos(place_id)
    if index >= len(items):
        return None
    try:
        data = _call(f"{items[index]['name']}/media", params={"maxWidthPx": width, "skipHttpRedirect": "true"})
    except (urllib.error.URLError, OSError, ValueError):
        return None
    uri = data.get("photoUri")
    if uri:
        cache.set(key, uri, _ttl())
    return uri


def credit(item):
    return f"Photo: {item['author'] or 'Google Maps user'}, Google Maps"
