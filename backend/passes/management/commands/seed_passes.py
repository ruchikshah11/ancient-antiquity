"""Create (or update) three sample combo passes. Prices are SAMPLE values: set real prices before going live.

    python manage.py seed_passes
"""
from decimal import Decimal

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from museums.models import Museum
from passes.models import ComboPass, ComboPassSite

NOTE = "Sample pass – set real prices."

PASSES = [
    {
        "slug": "agra-heritage-pass",
        "name": "Agra Heritage Pass",
        "description": "The Taj Mahal, Agra Fort and Fatehpur Sikri on one ticket, all on the same day. " + NOTE,
        "validity_days": 1,
        "featured": True,
        "prices": {"indian": "120", "foreign": "1800", "student": "60", "child": "0"},
        "sites": ["taj-mahal-agra", "agra-fort-agra", "fatehpur-sikri-fatehpur-sikri"],
    },
    {
        "slug": "delhi-heritage-pass",
        "name": "Delhi Heritage Pass",
        "description": "Red Fort, Qutub Minar and Humayun's Tomb on one ticket, all on the same day. " + NOTE,
        "validity_days": 1,
        "featured": True,
        "prices": {"indian": "100", "foreign": "1400", "student": "50", "child": "0"},
        "sites": ["red-fort-new-delhi", "qutub-minar-new-delhi", "humayuns-tomb-new-delhi"],
    },
    {
        "slug": "hampi-explorer-pass",
        "name": "Hampi Explorer Pass",
        "description": "Two days to explore the Group of Monuments at Hampi and the Archaeological Museum. " + NOTE,
        "validity_days": 2,
        "featured": False,
        "prices": {"indian": "60", "foreign": "800", "student": "30", "child": "0"},
        "sites": ["group-of-monuments-at-hampi-hampi", "archaeological-museum-hampi-hampi"],
    },
]


class Command(BaseCommand):
    help = "Create or update the three sample combo passes (Agra, Delhi, Hampi)."

    @transaction.atomic
    def handle(self, *args, **options):
        for spec in PASSES:
            museums = {m.slug: m for m in Museum.objects.filter(slug__in=spec["sites"])}
            missing = [s for s in spec["sites"] if s not in museums]
            if missing:
                raise CommandError(f"{spec['name']}: places not found: {', '.join(missing)}")
            combo, created = ComboPass.objects.update_or_create(
                slug=spec["slug"],
                defaults={
                    "name": spec["name"],
                    "description": spec["description"],
                    "image_url": museums[spec["sites"][0]].image_url,
                    "validity_days": spec["validity_days"],
                    "featured": spec["featured"],
                    "is_active": True,
                    **{f"price_{c}": Decimal(p) for c, p in spec["prices"].items()},
                },
            )
            combo.sites.all().delete()
            ComboPassSite.objects.bulk_create(
                [ComboPassSite(combo_pass=combo, museum=museums[s], sort_order=i) for i, s in enumerate(spec["sites"])]
            )
            self.stdout.write(f"{'Created' if created else 'Updated'} {combo.name} ({len(spec['sites'])} places)")
