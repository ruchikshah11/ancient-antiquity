"""Fetch museum descriptions and photos from Wikipedia / Wikimedia Commons.

Text is adapted from Wikipedia (CC BY-SA 4.0) and every photo keeps its author and licence,
which the site displays next to the content. Results are cached in data/wiki_cache.json so a
fresh database can be enriched again without internet access.
"""
import html
import json
import re
import time
import urllib.parse
import urllib.request
from pathlib import Path

API = "https://en.wikipedia.org/w/api.php"
USER_AGENT = "AncientAntiquity/1.0 (museum booking platform; contact: admin@ancientantiquity.in)"
CACHE_PATH = Path(__file__).resolve().parent / "data" / "wiki_cache.json"

STOP_WORDS = {
    "museum", "the", "of", "and", "archaeological", "government", "state", "national", "art", "gallery",
    "memorial", "palace", "centre", "center", "science", "india", "indian", "house", "new", "city", "fort",
    "institute", "complex", "sangrahalaya", "library", "regional", "technological", "industrial",
}
SKIP_SECTIONS = {
    "see also", "references", "external links", "gallery", "notes", "further reading",
    "bibliography", "sources", "citations", "footnotes", "images", "photo gallery",
}
BAD_IMAGE_WORDS = ("logo", "map", "flag", "icon", "signature", "emblem", "seal", "coat_of_arms", "locator", "symbol")
MAX_DESCRIPTION = 6000
MAX_GALLERY = 5


ASSUMED_AUTHOR = re.compile(r"No machine-readable author provided\.\s*(.+?)\s+assumed \(based on copyright claims\)\.?", re.I)
CREATED_BY = re.compile(r"^This (?:image|photo|file) was (?:created|taken) by (?:User:)?([^\s.]+).*", re.I | re.S)
MAX_ARTIST = 80


def clean_artist(artist):
    """Short author name for a photo credit. 'No machine-readable author provided. Faide~commonswiki
    assumed (based on copyright claims).' becomes 'Faide'; multi-line author notes join with '; '."""
    artist = ASSUMED_AUTHOR.sub(r"\1", artist or "")
    artist = CREATED_BY.sub(r"\1", artist.strip())
    artist = re.sub(r"~\w+wiki\b", "", artist)
    artist = "; ".join(re.sub(r"\s+", " ", line).strip() for line in artist.splitlines() if line.strip())
    artist = artist.strip(" .,;")
    if len(artist) > MAX_ARTIST:
        artist = artist[:MAX_ARTIST].rsplit(" ", 1)[0].rstrip(" .,;") + "…"
    return artist or "Unknown author"


def tidy_credit(credit):
    """Clean an already stored 'Photo: <artist>, <licence>, via Wikimedia Commons' credit."""
    m = re.match(r"Photo: (.*), ([^,]+), via Wikimedia Commons$", credit or "", re.S)
    return f"Photo: {clean_artist(m.group(1))}, {m.group(2)}, via Wikimedia Commons" if m else credit


def cache_key(name, city):
    return f"{name}|{city}"


def load_cache():
    if CACHE_PATH.exists():
        return json.loads(CACHE_PATH.read_text(encoding="utf-8"))
    return {}


def save_cache(cache):
    CACHE_PATH.write_text(json.dumps(cache, ensure_ascii=False, indent=1), encoding="utf-8")


def _get(params):
    params = {**params, "format": "json", "formatversion": "2", "maxlag": "5"}
    req = urllib.request.Request(f"{API}?{urllib.parse.urlencode(params)}", headers={"User-Agent": USER_AGENT})
    for attempt in range(3):
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                data = json.loads(r.read())
            if "error" in data and data["error"].get("code") == "maxlag":
                time.sleep(5)
                continue
            return data
        except OSError:
            if attempt == 2:
                raise
            time.sleep(2 * (attempt + 1))
    return {}


def _words(text):
    return set(re.findall(r"[a-z0-9]+", text.lower()))


def _score(title, name, city):
    """How likely a Wikipedia title is the article for this museum (0..~2)."""
    t = _words(title)
    distinct = _words(name) - STOP_WORDS
    if not distinct:
        distinct = _words(city)
    score = len(distinct & t) / len(distinct)
    if "museum" in name.lower() and ("museum" in t or "sangrahalaya" in t):
        score += 0.4
    if _words(city) & t:
        score += 0.2
    if "list" in t or "disambiguation" in title.lower():
        score -= 1
    return score


def find_article(name, city, override=None):
    if override:
        return override
    data = _get({
        "action": "query", "list": "search", "srsearch": f"{name} {city}",
        "srlimit": 5, "srnamespace": 0,
    })
    best, best_score = None, 0.6
    for hit in data.get("query", {}).get("search", []):
        s = _score(hit["title"], name, city)
        if s > best_score:
            best, best_score = hit["title"], s
    return best


def _clean_extract(text):
    """Wiki-format plain extract -> paragraphs with '## Heading' lines, minus reference sections."""
    out, skipping, length = [], False, 0
    for raw in text.split("\n"):
        line = raw.strip()
        if not line:
            continue
        m = re.match(r"^(=+)\s*(.*?)\s*=+$", line)
        if m:
            level, heading = len(m.group(1)), m.group(2)
            if level == 2:
                skipping = heading.lower() in SKIP_SECTIONS
            if skipping or level > 3:
                continue
            out.append(("## " if level == 2 else "### ") + heading)
            continue
        if skipping:
            continue
        if length + len(line) > MAX_DESCRIPTION:
            break
        out.append(line)
        length += len(line)
    while out and out[-1].startswith("#"):  # no dangling heading at the end
        out.pop()
    return "\n".join(out)


def _strip_html(value):
    return html.unescape(re.sub(r"<[^>]+>", "", value or "")).strip()


def _image_info(file_titles):
    if not file_titles:
        return {}
    data = _get({
        "action": "query", "titles": "|".join(file_titles), "prop": "imageinfo",
        "iiprop": "url|extmetadata|size", "iiurlwidth": 1280,
    })
    info = {}
    for page in data.get("query", {}).get("pages", []):
        ii = (page.get("imageinfo") or [{}])[0]
        if not ii.get("thumburl") or ii.get("width", 0) < 600:
            continue
        meta = ii.get("extmetadata", {})
        artist = clean_artist(_strip_html(meta.get("Artist", {}).get("value")))[:120]
        licence = _strip_html(meta.get("LicenseShortName", {}).get("value")) or "see source"
        caption = _strip_html(meta.get("ImageDescription", {}).get("value"))
        caption = re.sub(r"\s+", " ", caption)[:190]
        info[page["title"]] = {
            "url": ii["thumburl"].split("?")[0],
            "credit": f"Photo: {artist}, {licence}, via Wikimedia Commons",
            "source_url": ii.get("descriptionurl", ""),
            "caption": caption,
        }
    return info


def fetch_museum(name, city, override=None):
    """Return {'title','url','description','image','gallery'} or None when no good article exists."""
    title = find_article(name, city, override)
    if not title:
        return None
    data = _get({
        "action": "query", "titles": title, "redirects": 1,
        "prop": "extracts|pageimages|images|info", "inprop": "url",
        "explaintext": 1, "exsectionformat": "wiki",
        "piprop": "name", "imlimit": 50,
    })
    pages = data.get("query", {}).get("pages", [])
    if not pages or pages[0].get("missing"):
        return None
    page = pages[0]
    if "may refer to" in page.get("extract", "")[:300]:
        return None  # disambiguation page, not an article about the place

    lead = page.get("pageimage")
    files = [f"File:{lead}"] if lead else []
    for img in page.get("images", []):
        t = img["title"]
        low = t.lower()
        if low.endswith((".jpg", ".jpeg")) and not any(w in low for w in BAD_IMAGE_WORDS) and t not in files:
            files.append(t)
    info = _image_info(files[: MAX_GALLERY + 3])
    photos = [info[f] for f in files if f in info]

    return {
        "title": page["title"],
        "url": page.get("fullurl", ""),
        "description": _clean_extract(page.get("extract", "")),
        "image": photos[0] if photos else None,
        "gallery": photos[1: MAX_GALLERY + 1],
    }


def clear_wiki_content(museum):
    """Undo an earlier wrong match: drop Wikipedia text/photos, restore a basic description."""
    museum.description = f"{museum.name} in {museum.city.name}. {museum.tagline}".strip()
    museum.source_url = ""
    if "wikimedia.org" in museum.image_url:
        museum.image_url = museum.image_credit = museum.image_source_url = ""
    museum.save()
    museum.images.filter(url__contains="wikimedia.org").delete()
    return True


def apply_to_museum(museum, entry, force=False):
    """Copy a cache entry onto a museum. Hand-edited text/images are kept unless force=True."""
    from .models import MuseumImage

    changed = False
    from_wiki = bool(museum.source_url) and museum.source_url != entry.get("url")  # re-matched to a new article
    force = force or from_wiki
    if entry.get("description") and (force or len(museum.description) < 400):
        museum.description = entry["description"]
        museum.source_url = entry.get("url", "")
        changed = True
    img = entry.get("image")
    if img and (force or not museum.image_url or "wikimedia.org" in museum.image_url):
        museum.image_url = img["url"]
        museum.image_credit = img["credit"][:300]
        museum.image_source_url = img["source_url"]
        changed = True
    if changed:
        museum.save()
    if entry.get("gallery") and (force or not museum.images.exclude(url__contains="wikimedia.org").exists()):
        museum.images.filter(url__contains="wikimedia.org").delete()
        MuseumImage.objects.bulk_create([
            MuseumImage(museum=museum, url=g["url"], caption=g["caption"][:200], credit=g["credit"][:300],
                        source_url=g["source_url"], sort_order=i)
            for i, g in enumerate(entry["gallery"])
        ])
        changed = True
    return changed


# ---------- Extra photos for the place-page carousel ----------
COMMONS_API = "https://commons.wikimedia.org/w/api.php"
EXTRA_CACHE_PATH = CACHE_PATH.with_name("photos_cache.json")
MAX_PHOTOS = 12  # main photo + gallery shown in the carousel
NAME_NOISE = re.compile(r"\(.*?\)|&.*$|\b(museum|and|the|of|ruins|group|monuments?|at)\b", re.I)


def load_extra_cache():
    if EXTRA_CACHE_PATH.exists():
        return json.loads(EXTRA_CACHE_PATH.read_text(encoding="utf-8"))
    return {}


def save_extra_cache(cache):
    EXTRA_CACHE_PATH.write_text(json.dumps(cache, ensure_ascii=False, indent=1), encoding="utf-8")


def _commons_get(params):
    params = {**params, "format": "json", "formatversion": "2", "maxlag": "5"}
    req = urllib.request.Request(f"{COMMONS_API}?{urllib.parse.urlencode(params)}", headers={"User-Agent": USER_AGENT})
    for attempt in range(3):
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                return json.loads(r.read())
        except OSError:
            if attempt == 2:
                raise
            time.sleep(2)


def _photo_from_imageinfo(page):
    ii = (page.get("imageinfo") or [{}])[0]
    if not ii.get("thumburl") or ii.get("width", 0) < 800 or ii.get("width", 0) < ii.get("height", 0) * 0.9:
        return None  # too small, or portrait (crops badly in a wide carousel)
    meta = ii.get("extmetadata", {})
    artist = clean_artist(_strip_html(meta.get("Artist", {}).get("value")))[:120]
    licence = _strip_html(meta.get("LicenseShortName", {}).get("value")) or "see source"
    caption = re.sub(r"\s+", " ", _strip_html(meta.get("ImageDescription", {}).get("value")))[:190]
    url = ii["thumburl"].split("?")[0]
    return {
        "url": url,
        "credit": f"Photo: {artist}, {licence}, via Wikimedia Commons",
        "source_url": ii.get("descriptionurl", ""),
        "caption": caption,
    }


def _good_file(title):
    low = title.lower()
    return low.endswith((".jpg", ".jpeg")) and not any(w in low for w in BAD_IMAGE_WORDS)


def _infos(titles):
    out = []
    for i in range(0, len(titles), 40):
        data = _commons_get({
            "action": "query", "titles": "|".join(titles[i:i + 40]), "prop": "imageinfo",
            "iiprop": "url|extmetadata|size", "iiurlwidth": 1280,
        })
        by_title = {p["title"]: p for p in data.get("query", {}).get("pages", [])}
        out += [_photo_from_imageinfo(by_title[t]) for t in titles[i:i + 40] if t in by_title]
    return [p for p in out if p]


def article_photos(title):
    """All usable photos on a Wikipedia article (not just the first few)."""
    data = _get({"action": "query", "titles": title, "redirects": 1, "prop": "images", "imlimit": 100})
    pages = data.get("query", {}).get("pages", [])
    files = [i["title"] for p in pages for i in p.get("images", []) if _good_file(i["title"])]
    return _infos(files[:40])


def search_photos(name, city, limit=20):
    """Commons file search; keeps files whose title names the place (or its city for short names)."""
    core = re.sub(r"\s+", " ", NAME_NOISE.sub(" ", name)).strip(" ,-") or name
    # The file name must mention the place itself; the city alone ("…, Nagpur") matches anything there.
    generic = STOP_WORDS | {"central", "district", "site", "temple", "tomb", "garden", "gardens", "park", "hall"}
    words = {w for w in _words(core) if len(w) > 2 and w not in generic and w not in _words(city)}
    need = min(2, len(words))
    if not words:
        # Generic name ("Jhansi Fort", "Government Museum, Ajmer"): every word of the full name must appear.
        words = {w for w in _words(re.sub(r"\(.*?\)", " ", name)) if w not in {"the", "of", "and"}}
        need = len(words)
    data = _commons_get({
        "action": "query", "generator": "search", "gsrnamespace": 6, "gsrlimit": limit,
        "gsrsearch": f'"{core}" {city} filetype:bitmap',
        "prop": "imageinfo", "iiprop": "url|extmetadata|size", "iiurlwidth": 1280,
    })
    pages = sorted(data.get("query", {}).get("pages", []), key=lambda p: p.get("index", 0))
    keep = []
    for p in pages:
        # Whole words, at least two of the place's own words (or its only one).
        if not _good_file(p["title"]) or len(words & _words(p["title"])) < need:
            continue
        photo = _photo_from_imageinfo(p)
        if photo:
            keep.append(photo)
    return keep


def photo_key(url):
    """Same Commons file whatever host/size the URL uses (thumb. vs upload.wikimedia.org, 960px vs 1280px)."""
    m = re.search(r"/commons/(?:thumb/)?\w/\w\w/([^/]+)", url or "")
    return m.group(1).lower() if m else (url or "")


def apply_extra_photos(museum, photos):
    """Top a place up to MAX_PHOTOS with cached extra photos; never removes hand-added ones."""
    from .models import MuseumImage

    have = {photo_key(museum.image_url), *(photo_key(u) for u in museum.images.values_list("url", flat=True))}
    fresh = []
    for p in photos:
        if photo_key(p["url"]) not in have:
            have.add(photo_key(p["url"]))
            fresh.append(p)
    if not fresh:
        return 0
    added = 0
    if not museum.image_url:
        first = fresh.pop(0)
        museum.image_url, museum.image_credit, museum.image_source_url = first["url"], first["credit"][:300], first["source_url"]
        museum.save(update_fields=["image_url", "image_credit", "image_source_url"])
        added += 1
    room = MAX_PHOTOS - 1 - museum.images.count()
    start = (museum.images.order_by("-sort_order").values_list("sort_order", flat=True).first() or 0) + 1
    rows = [
        MuseumImage(museum=museum, url=p["url"], caption=p["caption"][:200], credit=p["credit"][:300],
                    source_url=p["source_url"], sort_order=start + i)
        for i, p in enumerate(fresh[:max(room, 0)])
    ]
    MuseumImage.objects.bulk_create(rows)
    return added + len(rows)
