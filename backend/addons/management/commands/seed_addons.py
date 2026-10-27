"""Give every active place a realistic set of add-ons. Prices are SAMPLE values: set real ones before going live.

    python manage.py seed_addons

Safe to run again: each place gets at most one add-on of each kind (updated in place, never duplicated).
Featured places count as "big" ones (Amer Fort, Mysore Palace...) and are priced at the top of each range.

    museums   audio guide ₹100/150 pp, camera ₹25, video ₹200, locker ₹20, wheelchair free (5 a day)
    monuments audio guide ₹150 pp (big ones), camera ₹25/50, video ₹250/300, wheelchair
    forts and palaces  audio guide ₹200 pp (big ones), camera ₹50, video ₹300/500, guided tour ₹400/600, wheelchair
"""
from decimal import Decimal

from django.core.management.base import BaseCommand
from django.db import transaction

from addons.models import AddOn
from museums.models import Museum

K, P = AddOn.Kind, AddOn.Per


def plan_for(museum):
    """[(kind, name, description, price, per, max_per_booking, daily_stock)] for one place."""
    big = museum.is_featured
    kind_of_place = museum.place_type
    items = []
    if kind_of_place == Museum.PlaceType.MUSEUM:
        items.append((K.AUDIO_GUIDE, "Audio guide", "Self-guided tour of the galleries in English or Hindi.",
                      150 if big else 100, P.PERSON, None, None))
        items.append((K.CAMERA, "Camera permit", "Still photography without flash or tripod.", 25, P.BOOKING, 2, None))
        items.append((K.VIDEO, "Video camera permit", "Hand-held video for personal use.", 200, P.BOOKING, 1, None))
        items.append((K.LOCKER, "Locker", "Leave bags and umbrellas at the cloakroom.", 20, P.BOOKING, 2, None))
    else:
        fort_or_palace = kind_of_place in (Museum.PlaceType.FORT, Museum.PlaceType.PALACE)
        if big:
            items.append((K.AUDIO_GUIDE, "Audio guide", "The story of the site on your phone or a handset.",
                          200 if fort_or_palace else 150, P.PERSON, None, None))
        items.append((K.CAMERA, "Camera permit", "Still photography for personal use.",
                      50 if fort_or_palace or big else 25, P.BOOKING, 2, None))
        items.append((K.VIDEO, "Video camera permit", "Hand-held video for personal use (no drones).",
                      (500 if big else 300) if fort_or_palace else (300 if big else 250), P.BOOKING, 1, None))
        if fort_or_palace:
            items.append((K.GUIDED_TOUR, "Guided tour", "About 90 minutes with an approved guide, up to 10 people.",
                          600 if big else 400, P.BOOKING, 1, None))
    items.append((K.WHEELCHAIR, "Wheelchair", "Free to use on the visit day. Limited each day, so book ahead.",
                  0, P.BOOKING, 2, 5))
    return items


class Command(BaseCommand):
    help = "Create or update sample add-ons (audio guide, camera, video, guided tour, locker, wheelchair) at every active place."

    @transaction.atomic
    def handle(self, *args, **options):
        created = updated = 0
        for museum in Museum.objects.filter(is_active=True):
            for sort, (kind, name, description, price, per, max_per, stock) in enumerate(plan_for(museum)):
                _, was_created = AddOn.objects.update_or_create(
                    museum=museum, kind=kind,
                    defaults={
                        "name": name, "description": description, "price": Decimal(price), "per": per,
                        "max_per_booking": max_per, "daily_stock": stock, "sort": sort,
                    },
                )
                created += was_created
                updated += not was_created
        self.stdout.write(self.style.SUCCESS(f"Add-ons: {created} created, {updated} updated."))
