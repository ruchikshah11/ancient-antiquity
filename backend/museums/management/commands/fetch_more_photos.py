"""Give every place more photos (up to 12, each with author/licence credit) for the place-page carousel.

    python manage.py fetch_more_photos            # apply data/photos_cache.json (no internet needed)
    python manage.py fetch_more_photos --fetch    # look up places missing from the cache, then apply
    python manage.py fetch_more_photos --refetch  # look up every place again

Photos come from the place's own Wikipedia article first, then a Wikimedia Commons search for the
place name. Hand-added photos are never removed; places are only topped up.
"""
import time

from django.core.management.base import BaseCommand

from museums import wikipedia
from museums.models import Museum, MuseumImage


class Command(BaseCommand):
    help = "Top up every place to 12 credited photos from Wikipedia / Wikimedia Commons"

    def add_arguments(self, parser):
        parser.add_argument("--fetch", action="store_true", help="Fetch places not yet in the cache")
        parser.add_argument("--refetch", action="store_true", help="Fetch every place again")

    def handle(self, fetch=False, refetch=False, **opts):
        wiki = wikipedia.load_cache()
        cache = wikipedia.load_extra_cache()
        museums = list(Museum.objects.select_related("city").order_by("pk"))

        if fetch or refetch:
            todo = [m for m in museums if refetch or wikipedia.cache_key(m.name, m.city.name) not in cache]
            self.stdout.write(f"Looking up photos for {len(todo)} places…")
            for n, m in enumerate(todo, 1):
                key = wikipedia.cache_key(m.name, m.city.name)
                entry = wiki.get(key)
                try:
                    photos = wikipedia.article_photos(entry["title"]) if entry else []
                    if len(photos) < wikipedia.MAX_PHOTOS:
                        photos += wikipedia.search_photos(m.name, m.city.name)
                except Exception as exc:  # network hiccup: leave uncached, retry next run
                    self.stderr.write(f"  {m.name}: {exc}")
                    continue
                seen, unique = set(), []
                for p in photos:
                    if p["url"] not in seen:
                        seen.add(p["url"])
                        unique.append(p)
                cache[key] = unique[:wikipedia.MAX_PHOTOS + 6]
                self.stdout.write(f"  [{n}/{len(todo)}] {m.name}: {len(unique)} photos")
                if n % 20 == 0:
                    wikipedia.save_extra_cache(cache)
                time.sleep(0.2)  # be polite to the API
            wikipedia.save_extra_cache(cache)

        # Tidy credits stored before clean_artist existed (photos added by hand keep their text).
        for m in Museum.objects.exclude(image_credit=""):
            if (tidy := wikipedia.tidy_credit(m.image_credit)) != m.image_credit:
                Museum.objects.filter(pk=m.pk).update(image_credit=tidy[:300])
        for img in MuseumImage.objects.filter(credit__contains="via Wikimedia Commons"):
            if (tidy := wikipedia.tidy_credit(img.credit)) != img.credit:
                MuseumImage.objects.filter(pk=img.pk).update(credit=tidy[:300])

        added = 0
        for m in museums:
            added += wikipedia.apply_extra_photos(m, cache.get(wikipedia.cache_key(m.name, m.city.name)) or [])
        few = sum(1 for m in Museum.objects.all() if (1 if m.image_url else 0) + m.images.count() < 5)
        self.stdout.write(self.style.SUCCESS(f"Added {added} photos. Places with fewer than 5 photos: {few}"))
