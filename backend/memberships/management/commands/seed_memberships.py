"""Create (or update) the three default Heritage Card plans. Prices are SAMPLE values: set real ones before going live.

    python manage.py seed_memberships
"""
from decimal import Decimal

from django.core.management.base import BaseCommand
from django.db import transaction

from memberships.models import MembershipPlan

PLANS = [
    {
        "slug": "heritage-card-individual",
        "name": "Heritage Card Individual",
        "description": "A year of discounted entry at every museum, fort, palace and monument on Ancient Antiquity.",
        "price": "1499", "discount_percent": 20, "max_visitors_per_booking": 1, "sort": 1,
    },
    {
        "slug": "heritage-card-family",
        "name": "Heritage Card Family",
        "description": "Bring the family: the discount covers up to four tickets on every booking for a year.",
        "price": "3999", "discount_percent": 25, "max_visitors_per_booking": 4, "sort": 2,
    },
    {
        "slug": "heritage-card-student",
        "name": "Heritage Card Student",
        "description": "For students: the biggest discount on your own ticket, all year. Carry your student ID.",
        "price": "599", "discount_percent": 30, "max_visitors_per_booking": 1, "sort": 3,
    },
]


class Command(BaseCommand):
    help = "Create or update the three default Heritage Card plans (Individual, Family, Student)."

    @transaction.atomic
    def handle(self, *args, **options):
        for spec in PLANS:
            plan, created = MembershipPlan.objects.update_or_create(
                slug=spec["slug"],
                defaults={
                    "name": spec["name"],
                    "description": spec["description"],
                    "price": Decimal(spec["price"]),
                    "duration_days": 365,
                    "discount_percent": spec["discount_percent"],
                    "free_entry": False,
                    "max_visitors_per_booking": spec["max_visitors_per_booking"],
                    "sort": spec["sort"],
                },
            )
            self.stdout.write(f"{'Created' if created else 'Updated'} {plan.name}")
        self.stdout.write(self.style.SUCCESS("Heritage Card plans ready."))
