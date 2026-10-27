"""Add detailed descriptions and photos (with credits) to museums from Wikipedia / Wikimedia Commons.

    python manage.py enrich_museums              # apply data/wiki_cache.json (no internet needed)
    python manage.py enrich_museums --fetch      # look up museums missing from the cache, then apply
    python manage.py enrich_museums --refetch    # look up every museum again
    python manage.py enrich_museums --force      # overwrite hand-edited descriptions/images too

A match report is written to data/wiki_matches.csv. If a museum matched the wrong article, add
the correct article title to WIKI_TITLES below (or None to skip it) and run with --refetch.
"""
import csv
import time

from django.core.management.base import BaseCommand

from museums import wikipedia
from museums.models import Museum

# Museum name -> exact Wikipedia article title, where search alone picks the wrong page.
# None = no suitable article; keep the museum's own short description and no photo.
WIKI_TITLES = {
    "National Museum": "National Museum of India",
    "Indian Museum": "Indian Museum",
    "National Science Centre": "National Science Centre, Delhi",
    "Archaeological Museum, Chanderi": "Chanderi",
    "Archaeological Museum, Old Goa": "Old Goa",
    "Archaeological Museum, Ropar": "Rupnagar",
    "Archaeological Museum, Dholavira": "Dholavira",
    "Archaeological Museum, Lalitgiri": "Lalitagiri",
    "Government Museum, Bharatpur": "Lohagarh Fort",
    "Puducherry Museum": "Pondicherry Museum",
    "State Museum, Bhopal": "State Museum, Bhopal",
    "Vivekananda House": "Vivekanandar Illam",
    "Victoria Jubilee Museum": "Bapu Museum, Vijayawada",
    "Ramnagar Fort & Museum": "Ramnagar Fort",
    "Mehrangarh Fort & Museum": "Mehrangarh",
    "Junagarh Fort & Museum": "Junagarh Fort",
    "Purana Qila & Museum": "Purana Qila",
    "Mattancherry Palace (Dutch Palace)": "Mattancherry Palace",
    "Anand Bhawan": "Anand Bhavan",
    "Cellular Jail National Memorial": "Cellular Jail",
    "Gandhi Smarak Sangrahalaya (Sabarmati Ashram)": "Sabarmati Ashram",
    "Jaganmohan Palace Art Gallery": "Jaganmohan Palace",
    "National Crafts Museum & Hastkala Academy": "National Handicrafts and Handlooms Museum",
    "Pradhanmantri Sangrahalaya": "Prime Ministers' Museum and Library",
    "Rabindra Bharati Museum (Jorasanko Thakurbari)": "Jorasanko Thakur Bari",
    "Samudrika Naval Marine Museum": "Samudrika Naval Marine Museum",
    "Shahu Chhatrapati Museum (New Palace)": "New Palace, Kolhapur",
    "Srikrishna Science Centre": "Shrikrishna Science Centre",
    "Swatantrata Sangram Sangrahalaya": None,  # the Red Fort has its own page now
    "Archaeological Museum, Fatehpur Sikri": None,  # Fatehpur Sikri has its own page now
    "Government Museum, Bharatpur": None,  # only the Lohagarh Fort article exists
    # forts and monuments whose article titles differ from the place name
    "Dhamek Stupa & Sarnath Ruins": "Dhamek Stupa",
    "Buddhist Monuments at Sanchi": "Sanchi",
    "Jahaz Mahal, Mandu": "Jahaz Mahal",
    "Rock Shelters of Bhimbetka": "Bhimbetka rock shelters",
    "Sun Temple Modhera": "Sun Temple, Modhera",
    "Group of Monuments at Hampi": "Hampi",
    "Pattadakal Group of Monuments": "Pattadakal",
    "Nalanda Mahavihara": "Nalanda mahavihara",
    "Khajuraho Group of Monuments": "Khajuraho Group of Monuments",
    "Red Fort": "Red Fort",
    "Qutub Minar": "Qutb Minar",
    "Amer Fort": "Amber Fort",
    "Itmad-ud-Daulah's Tomb": "Itmad Ud Daulah",
    "Safdarjung's Tomb": "Tomb of Safdar Jang",
    "Jhansi Fort": "Jhansi Fort",
    "Diu Fort": "Diu Fortress",
    "Kangra Fort": "Kangra Fort",
    "Gwalior Fort": "Gwalior Fort",
    "Chittorgarh Fort": "Chittor Fort",
    "Gingee Fort": "Gingee Fort",
    "Bidar Fort": "Bidar Fort",
    "Chitradurga Fort": "Chitradurga Fort",
    "Chandragiri Fort": "Chandragiri Fort, Andhra Pradesh",
    "Cooch Behar Palace": "Cooch Behar Palace",
    "Pinjore Gardens": "Yadavindra Gardens",
    "Bangalore Palace": "Bengaluru Palace",
    "Ross Island": "Ross Island, South Andaman district",
    "Rabdentse Ruins": "Rabdentse",
    "Vikramshila": "Vikramashila",
    "Tripura State Museum (Ujjayanta Palace)": "Ujjayanta Palace",
    "Jharkhand State Museum": "State Museum, Ranchi",
    "Anthropological Museum": None,
    "Marine Museum": None,
    "Kangra Art Museum": None,
    "Le Corbusier Centre": None,
    "Diu Museum": None,
    "Thanjavur Art Gallery": None,
    "Central Museum, Nagpur": None,
    "Government Museum, Ajmer": None,
    "Shri Pratap Singh Museum": None,
    "Nicholas Roerich Art Gallery": None,
}


class Command(BaseCommand):
    help = "Enrich museums with Wikipedia descriptions and Wikimedia Commons photos"

    def add_arguments(self, parser):
        parser.add_argument("--fetch", action="store_true", help="Fetch museums not yet in the cache")
        parser.add_argument("--refetch", action="store_true", help="Fetch every museum again")
        parser.add_argument("--force", action="store_true", help="Overwrite hand-edited text and images")

    def handle(self, fetch=False, refetch=False, force=False, **opts):
        cache = wikipedia.load_cache()
        museums = list(Museum.objects.select_related("city"))

        if fetch or refetch:
            # Overrides always win over whatever an earlier search cached.
            for m in museums:
                key = wikipedia.cache_key(m.name, m.city.name)
                want = WIKI_TITLES.get(m.name, "")
                if want == "" or key not in cache:
                    continue
                cached = cache[key]
                if want is None and cached is not None:
                    del cache[key]
                elif want and (cached is None or cached.get("requested") != want):
                    del cache[key]
            todo = [m for m in museums if refetch or wikipedia.cache_key(m.name, m.city.name) not in cache]
            self.stdout.write(f"Fetching {len(todo)} museums from Wikipedia…")
            for n, m in enumerate(todo, 1):
                key = wikipedia.cache_key(m.name, m.city.name)
                override = WIKI_TITLES.get(m.name, "")
                if override is None:
                    cache[key] = None
                    continue
                try:
                    cache[key] = wikipedia.fetch_museum(m.name, m.city.name, override or None)
                    if cache[key] and override:
                        cache[key]["requested"] = override
                except Exception as exc:  # network hiccup: leave uncached, retry next run
                    self.stderr.write(f"  {m.name}: {exc}")
                    continue
                hit = cache[key]
                self.stdout.write(f"  [{n}/{len(todo)}] {m.name} -> {hit['title'] if hit else 'no match'}")
                if n % 20 == 0:
                    wikipedia.save_cache(cache)
                time.sleep(0.2)  # be polite to the API
            wikipedia.save_cache(cache)

        # A museum inside a fort/monument must not reuse that place's article: the fort/monument keeps it.
        owner = {}
        for m in sorted(museums, key=lambda m: m.place_type == "museum"):
            entry = cache.get(wikipedia.cache_key(m.name, m.city.name))
            if entry:
                owner.setdefault(entry["url"], m.pk)

        applied = 0
        report = wikipedia.CACHE_PATH.with_name("wiki_matches.csv")
        with open(report, "w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(["museum", "city", "wikipedia_title", "url", "has_image", "gallery", "description_chars"])
            for m in museums:
                entry = cache.get(wikipedia.cache_key(m.name, m.city.name))
                if entry and owner.get(entry["url"]) != m.pk:
                    entry = None  # duplicate of another place's article
                w.writerow([
                    m.name, m.city.name, entry["title"] if entry else "", entry["url"] if entry else "",
                    bool(entry and entry["image"]), len(entry["gallery"]) if entry else 0,
                    len(entry["description"]) if entry else 0,
                ])
                if entry and wikipedia.apply_to_museum(m, entry, force=force):
                    applied += 1
                elif not entry and m.source_url and wikipedia.clear_wiki_content(m):
                    applied += 1

        # enrich rebuilds the Wikipedia gallery; put the carousel's extra photos back (see fetch_more_photos).
        extra = wikipedia.load_extra_cache()
        for m in museums:
            wikipedia.apply_extra_photos(m, extra.get(wikipedia.cache_key(m.name, m.city.name)) or [])

        with_img = Museum.objects.exclude(image_url="").count()
        self.stdout.write(self.style.SUCCESS(
            f"Updated {applied} museums. {with_img}/{len(museums)} have a photo. Report: {report}"
        ))
