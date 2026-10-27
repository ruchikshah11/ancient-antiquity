"""Replace all visitor activity with realistic sample data.

    python manage.py seed_demo_data --wipe --yes

1. Wipes every booking, payment, review, request, message, order and log, and every user except the
   three demo logins (admin@, staff@, visitor@ancientantiquity.in). Places, ticket prices, slots, events,
   combo passes, add-ons and Heritage Card plans are kept.
2. Creates 14 people (12 visitors, a museum staff member and a tour operator) and about four months of
   activity through the real services, so prices, discounts, refunds and receipts are computed exactly as
   on the live site: past visits with check-ins and reviews, upcoming bookings, cancellations with refunds,
   add-ons, promo codes, Heritage Cards, donations with 80G receipts, event tickets, combo passes, group
   and counter sales, favourites, trip plans, support messages and funnel analytics.
3. Writes the new logins (with fresh random passwords) into docs/LOGIN_DETAILS.md.
"""
import contextlib
import datetime
import logging
import random
import secrets
import string
from decimal import Decimal
from pathlib import Path
from unittest import mock

from django.apps import apps
from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError as DjangoValidationError
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.db.models import ProtectedError
from django.test import override_settings
from django.utils import timezone
from rest_framework.exceptions import ValidationError

User = get_user_model()
KEEP_EMAILS = ("admin@ancientantiquity.in", "staff@ancientantiquity.in", "visitor@ancientantiquity.in")

# Whole apps whose rows are all visitor activity or logs.
WIPE_APPS = ("analytics", "assistant", "audit", "notifications", "support", "trips", "grouprequests", "schools",
             "bookings", "donations")
# Single models elsewhere (the rest of those apps is configuration and stays).
WIPE_MODELS = ("events.WaitlistEntry", "promotions.VoucherRedemption", "promotions.PromoRedemption",
               "promotions.GiftVoucher", "promotions.PromoCode", "museums.ReviewPhoto", "museums.Review",
               "partners.AgentPayment", "partners.Settlement", "partners.KioskDevice", "partners.AgentProfile",
               "passes.PassOrder", "memberships.Membership", "accounts.LoginOTP")

PEOPLE = [
    # first, last, city, persona
    ("Aarav", "Mehta", "Ahmedabad", "family"),
    ("Priya", "Sharma", "Jaipur", "member"),
    ("Rohan", "Iyer", "Chennai", "solo"),
    ("Ananya", "Das", "Kolkata", "student"),
    ("Kabir", "Singh", "Amritsar", "couple"),
    ("Meera", "Nair", "Kochi", "member"),
    ("Vikram", "Reddy", "Hyderabad", "family"),
    ("Sneha", "Kulkarni", "Pune", "couple"),
    ("Arjun", "Patel", "Vadodara", "solo"),
    ("Fatima", "Sheikh", "Lucknow", "student"),
    ("Ishaan", "Gupta", "New Delhi", "member"),
    ("Kavya", "Joshi", "Udaipur", "couple"),
]
STAFF_PERSON = ("Neha", "Verma", "New Delhi")

# Bulk sample visitors: names from across India plus some foreign tourists.
FIRST_NAMES = (
    "Aarav Aditya Akash Amit Anil Arjun Ashok Deepak Dev Dhruv Ganesh Gaurav Harsh Hemant Ishaan Jatin Karan Kunal "
    "Lokesh Manish Mohit Naveen Nikhil Om Pranav Rahul Raj Rajesh Ravi Rohit Sachin Sanjay Saurabh Shiv Siddharth "
    "Sunil Tarun Varun Vijay Vikas Vinod Yash Anand Balaji Karthik Murali Prakash Ramesh Senthil Srinivas Venkat "
    "Arnab Debashish Soumya Subhash Gurpreet Harjeet Manpreet Imran Faisal Salman Irfan Joseph Thomas "
    "Aanya Aditi Aishwarya Ananya Anjali Anushka Bhavna Deepa Divya Gauri Isha Jyoti Kavya Kirti Lakshmi Madhuri "
    "Meena Meera Neha Nidhi Pallavi Pooja Priya Radha Rashmi Riya Sakshi Sanya Shreya Simran Sneha Sonali Swati "
    "Tanvi Trisha Uma Vaishnavi Vidya Anitha Deepika Kavitha Revathi Sangeetha Swetha Moumita Payel Rituparna "
    "Harleen Jaspreet Navneet Ayesha Farah Nazia Sana Mary Reena"
).split()
SURNAMES = (
    "Sharma Verma Gupta Agarwal Singh Yadav Mishra Pandey Tiwari Chauhan Rathore Shekhawat Mehta Patel Shah Desai "
    "Joshi Trivedi Parmar Kulkarni Deshpande Patil Jadhav Pawar Kale Iyer Iyengar Nair Menon Pillai Reddy Rao "
    "Naidu Krishnan Subramanian Raman Das Bose Banerjee Chatterjee Mukherjee Ghosh Sen Dutta Roy Gill Sandhu "
    "Dhillon Grewal Kaur Khan Sheikh Ansari Qureshi Siddiqui D'Souza Fernandes Pereira Thomas George Mathew "
    "Bhatt Kapoor Malhotra Khanna Arora Saxena Srivastava Tripathi Dubey Bansal Jain Goel Mittal"
).split()
FOREIGN = [("Emma", "Wilson"), ("Liam", "Brown"), ("Sophie", "Martin"), ("Lukas", "Müller"), ("Yuki", "Tanaka"),
           ("Olivia", "Taylor"), ("Noah", "Anderson"), ("Chloé", "Dubois"), ("Mateo", "García"), ("Hannah", "Schmidt"),
           ("James", "Smith"), ("Ava", "Johnson"), ("Haruto", "Sato"), ("Isabella", "Rossi"), ("Ethan", "Clarke")]
EMAIL_DOMAINS = [("gmail.com", 55), ("yahoo.co.in", 10), ("yahoo.com", 6), ("outlook.com", 10), ("hotmail.com", 6),
                 ("rediffmail.com", 5), ("icloud.com", 5), ("proton.me", 3)]
AGENT_PERSON = ("Rajesh", "Khanna", "Jaipur", "Incredible Heritage Tours Pvt. Ltd.")
WALK_IN_NAMES = ["Suresh Yadav", "Pooja Rawat", "Amit Chauhan", "Lakshmi Pillai", "Deepak Saini", "Ritu Bansal",
                 "Manoj Tiwari", "Sunita Devi", "Harish Rao", "Nisha Kapoor", "John Miller", "Emma Schmidt"]

REVIEWS = {
    "museum": [
        ("Beautifully curated", "The galleries are well laid out and the labels are clear. Plan at least two hours."),
        ("Worth every minute", "Loved the sculpture and coin sections. Booking a slot online meant no queue at all."),
        ("Great for kids", "Our children enjoyed the interactive corners. Clean washrooms and a decent cafe."),
        ("Hidden gem", "Far fewer crowds than we expected. Some galleries were closed for renovation."),
        ("बहुत अच्छा अनुभव", "संग्रह शानदार है और स्टाफ मददगार था। ऑडियो गाइड ज़रूर लें।"),
    ],
    "fort": [
        ("Breathtaking views", "Go early in the morning; the ramparts are stunning and it stays cool till ten."),
        ("History comes alive", "We took the guided tour and it made a huge difference. Wear comfortable shoes."),
        ("Massive and magnificent", "Easily three hours. The QR ticket scanned in seconds at the gate."),
        ("Good but crowded", "Weekend afternoon was busy. Signage could be better inside the inner palaces."),
        ("शानदार किला", "दीवारें और नज़ारा अद्भुत है। सुबह जल्दी जाएँ, भीड़ कम रहती है।"),
    ],
    "palace": [
        ("Royal and elegant", "The courtyards and mirror work are gorgeous. Photography permit was worth it."),
        ("Lovely afternoon", "Well maintained rooms and gardens. The audio guide explains every hall."),
        ("A must in the city", "Stunning architecture. Café on site is a bit pricey but the view makes up for it."),
        ("Beautiful but busy", "Arrive in the first slot to enjoy it before tour groups come in."),
    ],
    "monument": [
        ("Simply stunning", "The carvings are incredible up close. Sunset light is magical."),
        ("Peaceful and grand", "Well kept lawns and clear information boards. Very easy entry with the e-ticket."),
        ("Must visit", "Spent two hours and could have stayed longer. Carry water in summer."),
        ("ज़रूर देखें", "बहुत सुंदर स्मारक है। टिकट ऑनलाइन लेना आसान था।"),
    ],
}
# Extra sentences mixed into bulk reviews so comments read differently.
REVIEW_EXTRAS = [
    "Parking was easy to find.", "Carry a water bottle in summer.", "The audio guide was worth it.",
    "Staff at the gate were polite and quick.", "Washrooms were clean.", "Go on a weekday to avoid crowds.",
    "Our guide knew every story behind the walls.", "Sunset views are spectacular.", "A bit crowded near the main hall.",
    "Wheelchair access was better than expected.", "The café near the exit serves good chai.",
    "Kids loved it.", "Signboards could be clearer.", "Online ticket made entry super quick.",
    "बच्चों को बहुत पसंद आया।", "पार्किंग की सुविधा अच्छी थी।", "गाइड बहुत जानकार थे।",
]
RATINGS = [Decimal(x) for x in ("5", "5", "4.5", "4.5", "4.5", "4", "4", "4", "3.5", "3")]


def strong_password(word):
    alnum = string.ascii_letters + string.digits
    return f"{word}-{''.join(secrets.choice(alnum) for _ in range(5))}-{secrets.randbelow(90) + 10}!"


class Command(BaseCommand):
    help = "Wipe visitor activity and create realistic sample users, bookings, reviews and more"

    def add_arguments(self, parser):
        parser.add_argument("--wipe", action="store_true", help="Replace everything: confirms existing activity is deleted")
        parser.add_argument("--mass-bookings", type=int, default=0,
                            help="With --append: add this many bookings (e.g. 1000000) spread over the existing sample visitors")
        parser.add_argument("--append", action="store_true",
                            help="Keep all existing data and only ADD --users / --mass-users more visitors with their bookings")
        parser.add_argument("--yes", action="store_true", help="Don't ask for confirmation")
        parser.add_argument("--seed", type=int, default=2026, help="Random seed (same seed = same data shape)")
        parser.add_argument("--users", type=int, default=1000, help="Extra sample visitors sharing one password (default 1000)")
        parser.add_argument("--mass-users", type=int, default=0,
                            help="Even more visitors (e.g. 100000), written in fast batches with their bookings and reviews")

    # ------------------------------------------------------------------ entry point

    def handle(self, wipe, yes, seed, users=1000, mass_users=0, append=False, mass_bookings=0, **opts):
        if wipe == append:
            raise CommandError("Choose one: --wipe (replace ALL bookings, reviews and users except the 3 demo logins) "
                               "or --append (keep everything, add more visitors).")
        if wipe and not yes and input("Delete all visitor activity and users? Type 'yes': ").strip().lower() != "yes":
            raise CommandError("Cancelled.")
        self.appending = append
        self.mass_bookings = mass_bookings
        self.rng = random.Random(seed)
        self.now = timezone.now()
        self.today = timezone.localdate()
        self.skipped = []
        self.counts = {}
        self.bulk_count = users
        self.mass_count = mass_users
        self.mass_rows = []
        self.bulk_users = []
        self.bulk_password = ""
        # Emails go to memory, not to backend/sent_emails or real inboxes, while seeding.
        with override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend", SMS_PROVIDER="console",
                               RAZORPAY_KEY_ID="", RAZORPAY_KEY_SECRET=""):
            logging.disable(logging.INFO)  # SMS/WhatsApp console messages for every seeded booking
            try:
                if self.appending:
                    self.append_visitors()  # commits batch by batch: nothing is deleted, progress is kept
                else:
                    with transaction.atomic():
                        self.wipe()
                        self.seed()
            finally:
                logging.disable(logging.NOTSET)
        if self.appending:
            self.append_csv()
        else:
            self.write_login_details()
        self.report()

    # ------------------------------------------------------------------ wipe

    def wipe(self):
        models = [m for app in WIPE_APPS if app in {c.label for c in apps.get_app_configs()}
                  for m in apps.get_app_config(app).get_models()]
        for label in WIPE_MODELS:
            try:
                models.append(apps.get_model(label))
            except LookupError:
                pass
        # Delete in passes until nothing is left; protected rows go once what protects them is gone.
        remaining = list(models)
        for _ in range(6):
            blocked = []
            for model in remaining:
                try:
                    model.objects.all().delete()
                except ProtectedError:
                    blocked.append(model)
            if not blocked:
                break
            remaining = blocked
        else:
            raise CommandError(f"Could not delete: {', '.join(m._meta.label for m in remaining)}")
        deleted, _ = User.objects.exclude(email__in=KEEP_EMAILS).delete()
        self.stdout.write(f"Wiped visitor activity and {deleted} other rows of user data.")

    # ------------------------------------------------------------------ helpers

    @contextlib.contextmanager
    def at(self, moment):
        """Run code as if it were `moment` (created_at, paid_at, check-in times all follow)."""
        with mock.patch("django.utils.timezone.now", return_value=moment):
            yield

    def moment(self, day, hour, minute=0):
        return timezone.make_aware(datetime.datetime.combine(day, datetime.time(hour, minute)))

    def count(self, key, n=1):
        self.counts[key] = self.counts.get(key, 0) + n

    def phone(self):
        while True:
            number = f"{self.rng.choice('6789')}{self.rng.randrange(10**8, 10**9)}"
            if number not in self.used_phones:
                self.used_phones.add(number)
                return number

    def pan(self, last_name):
        letters = string.ascii_uppercase
        return f"{''.join(self.rng.choice(letters) for _ in range(3))}P{last_name[0].upper()}{self.rng.randrange(1000, 9999)}{self.rng.choice(letters)}"

    def email_for(self, first, last, domain=None):
        """A realistic, unique address (gmail.com, yahoo.co.in …). Such addresses may belong to real people,
        which is why every seeded account is flagged is_sample and never emailed or texted (notifications.mail)."""
        def ascii_only(text):
            return "".join(ch for ch in text.lower() if ch.isascii() and (ch.isalnum() or ch in "._"))

        base = ascii_only(f"{first}.{last}") or "visitor"
        domain = domain or self.rng.choices([d for d, _ in EMAIL_DOMAINS], [w for _, w in EMAIL_DOMAINS])[0]
        styles = [base, base.replace(".", ""), base.replace(".", "_"), f"{base}{self.rng.randint(1, 99)}",
                  f"{ascii_only(first)[:1]}{ascii_only(last)}{self.rng.randint(70, 2005)}"]
        for _ in range(20):
            email = f"{self.rng.choice(styles)}@{domain}"
            if email not in self.used_emails:
                self.used_emails.add(email)
                return email
            styles.append(f"{base}{self.rng.randint(100, 9999)}")
        raise CommandError("Could not make a unique email")

    def make_user(self, first, last, city, role=User.Role.VISITOR, word="Heritage", domain=None):
        email = self.email_for(first, last, domain)
        password = strong_password(word)
        user = User.objects.create_user(email=email, password=password, role=role, first_name=first, last_name=last,
                                        phone=self.phone(), is_sample=True)
        with self.at(self.now - datetime.timedelta(days=self.rng.randint(100, 140))):
            User.objects.filter(pk=user.pk).update(date_joined=timezone.now(),
                                                    last_login=self.now - datetime.timedelta(days=self.rng.randint(0, 6)))
        self.logins.append({"name": f"{first} {last}", "email": email, "password": password, "role": user.get_role_display(),
                            "city": city, "notes": ""})
        return user

    def places(self):
        from museums.models import Museum

        qs = (Museum.objects.filter(is_active=True, slots__is_active=True, ticket_types__is_active=True)
              .select_related("city__state").distinct())
        return list(qs)

    def ticket_mix(self, museum, persona):
        types = list(museum.ticket_types.filter(is_active=True).order_by("sort_order", "id"))
        if not types:
            return []

        def find(*words):
            for t in types:
                if any(w in t.name.lower() for w in words):
                    return t
            return None

        adult = find("indian", "adult") or types[0]
        child, student, foreign = find("child"), find("student"), find("foreign")
        r = self.rng.random()
        if persona == "family":
            mix = [(adult, 2)] + ([(child, self.rng.randint(1, 2))] if child else [])
        elif persona == "student":
            mix = [(student or adult, self.rng.randint(1, 3))]
        elif persona == "couple":
            mix = [(adult, 2)]
        elif (persona == "foreign" or r < 0.15) and foreign:
            mix = [(foreign, 2)]
        else:
            mix = [(adult, self.rng.randint(1, 2))]
        return [{"ticket_type": t, "quantity": q} for t, q in mix if t]

    def open_visit(self, museum, start, end):
        """A random (date, slot) between start and end when the place is open."""
        from bookings import services

        slots = list(museum.slots.filter(is_active=True).order_by("start_time"))
        if not slots:
            return None
        for _ in range(25):
            day = start + datetime.timedelta(days=self.rng.randint(0, max((end - start).days, 0)))
            slot = self.rng.choice(slots[: max(2, len(slots) - 1)])
            if services.closure_error(museum, slot, day) is None:
                return day, slot
        return None

    # ------------------------------------------------------------------ seeding

    def seed(self):
        from museums.models import Museum

        self.logins = []
        self.used_emails = set(User.objects.values_list("email", flat=True))
        self.used_phones = set()
        self.admin = User.objects.get(email="admin@ancientantiquity.in")
        self.demo_staff = User.objects.get(email="staff@ancientantiquity.in")
        self.demo_visitor = User.objects.get(email="visitor@ancientantiquity.in")
        all_places = self.places()
        if not all_places:
            raise CommandError("No bookable places found (need active slots and ticket types).")
        featured = [p for p in all_places if p.is_featured] or all_places

        self.seed_promotions(all_places)

        # People
        visitors = []
        for first, last, city, persona in PEOPLE:
            user = self.make_user(first, last, city)
            user.persona, user.home_city = persona, city
            visitors.append(user)
        self.demo_visitor.persona, self.demo_visitor.home_city = "couple", "New Delhi"
        staff_places = [m for m in Museum.objects.filter(slug__in=[
            "national-museum-new-delhi", "red-fort-new-delhi", "qutub-minar-new-delhi", "humayuns-tomb-new-delhi",
        ]) if m in all_places] or featured[:3]
        # Staff use a company address on the site's own domain.
        staff = self.make_user(*STAFF_PERSON, role=User.Role.STAFF, word="Gatekeeper", domain="ancientantiquity.in")
        for museum in staff_places:
            museum.staff.add(staff)
        self.logins[-1]["notes"] = "Museum staff for " + ", ".join(m.name for m in staff_places)
        self.staff = staff
        agent = self.seed_agent()
        self.seed_kiosk(staff_places)

        self.seed_memberships(visitors)

        # Online bookings: past visits (checked in, a few no-shows and cancellations) and upcoming ones.
        for user in visitors + [self.demo_visitor]:
            home = [p for p in all_places if p.city.name == user.home_city]
            state_places = [p for p in all_places if user.home_city and p.city.state.name in self.state_of(user.home_city)]
            pool = (home + state_places) * 2 + featured
            for _ in range(self.rng.randint(5, 9)):
                museum = self.rng.choice(pool)
                past = self.rng.random() < 0.65
                self.online_booking(user, museum, past=past)

        self.seed_bulk_visitors(self.bulk_count, all_places, featured)
        self.seed_counter_sales(staff_places)
        self.seed_groups(featured)
        self.seed_group_requests(visitors, featured)
        self.seed_agent_bookings(agent, featured)
        self.seed_events(visitors)
        self.seed_passes(visitors)
        self.seed_reviews()
        self.seed_donations(visitors, featured)
        self.seed_favourites_and_trips(visitors, all_places)
        self.seed_support(visitors)
        self.seed_waitlist(visitors)
        self.seed_schools(visitors, all_places)
        self.seed_funnel(all_places)
        # Last-but-one: written in bulk, after reviews/funnel (which work booking by booking), before settlements.
        self.seed_mass(self.mass_count, all_places, featured)
        self.seed_settlements()

    def seed_bulk_visitors(self, n, places, featured):
        """`n` more visitors sharing one password; about 60% have 1-3 bookings (past and upcoming)."""
        from django.contrib.auth.hashers import make_password

        if n <= 0:
            return
        self.bulk_password = self.bulk_password or strong_password("Explorer")
        hashed = make_password(self.bulk_password)  # hash once: Argon2 per user would take minutes
        cities = sorted({p.city.name for p in places})
        tourist_cities = [c for c in ("New Delhi", "Jaipur", "Agra", "Mumbai", "Udaipur") if c in cities] or cities
        users = []
        for i in range(n):
            if i % 25 == 0:
                first, last = self.rng.choice(FOREIGN)
                city, persona = self.rng.choice(tourist_cities), "foreign"
            else:
                first, last = self.rng.choice(FIRST_NAMES), self.rng.choice(SURNAMES)
                city = self.rng.choice(cities)
                persona = self.rng.choice(["solo", "couple", "couple", "family", "family", "student"])
            joined = self.now - datetime.timedelta(days=self.rng.randint(1, 540), minutes=self.rng.randint(0, 1440))
            seen = joined + datetime.timedelta(days=self.rng.randint(0, max(1, (self.now - joined).days)))
            user = User(email=self.email_for(first, last), first_name=first, last_name=last, phone=self.phone(),
                        password=hashed, role=User.Role.VISITOR, is_sample=True, date_joined=joined,
                        last_login=min(seen, self.now) if self.rng.random() < 0.85 else None)
            users.append((user, persona, city))
        created = User.objects.bulk_create([u for u, _, _ in users], batch_size=500)
        for user, (_, persona, city) in zip(created, users):
            user.persona, user.home_city = persona, city
        self.bulk_users = created
        self.count("bulk visitors", len(created))
        by_city = {}
        for p in places:
            by_city.setdefault(p.city.name, []).append(p)
        for user in created:
            if self.rng.random() > 0.6:
                continue
            pool = by_city.get(user.home_city, []) * 3 + featured
            for _ in range(self.rng.choices([1, 2, 3], [55, 30, 15])[0]):
                self.online_booking(user, self.rng.choice(pool), past=self.rng.random() < 0.6)

    @contextlib.contextmanager
    def keep_timestamps(self, *models):
        """Let bulk_create store the created_at values we set (auto_now_add would overwrite them)."""
        fields = [f for m in models for f in m._meta.concrete_fields if getattr(f, "auto_now_add", False) or getattr(f, "auto_now", False)]
        saved = [(f, f.auto_now_add, f.auto_now) for f in fields]
        for f in fields:
            f.auto_now_add = f.auto_now = False
        try:
            yield
        finally:
            for f, add, now in saved:
                f.auto_now_add, f.auto_now = add, now

    def seed_mass(self, n, places, featured):
        """`n` visitors written in batches, with ~1.2 bookings each (priced by the real ticket prices and price
        rules, skipping closures), check-ins, cancellations with refunds and reviews. Minutes instead of hours."""
        from bookings import services
        from bookings.models import Booking, BookingItem, GateScan, generate_reference
        from museums.models import PriceRule, Review

        if n <= 0:
            return
        password = self.bulk_password or strong_password("Explorer")
        self.bulk_password = password
        from django.contrib.auth.hashers import make_password

        hashed = make_password(password)
        cities = sorted({p.city.name for p in places})
        weights = [8 if p.is_featured else 1 for p in places]
        info = {}
        for p in places:
            info[p.pk] = {
                "slots": list(p.slots.filter(is_active=True).order_by("start_time")),
                "tickets": list(p.ticket_types.filter(is_active=True).order_by("sort_order", "id")),
                "rules": list(PriceRule.objects.filter(museum=p, is_active=True).order_by("-priority", "-id")),
            }
        closure_cache = {}

        def closed(museum, slot, day):
            key = (museum.pk, day)
            if key not in closure_cache:
                closure_cache[key] = museum.closure_on(day)
            c = closure_cache[key]
            return c["closed"] or slot.id in c["slots"]

        checkers = {p.pk: (self.staff if p in self.staff.assigned_museums.all() else self.admin) for p in places}
        refs = set(Booking.objects.values_list("reference", flat=True))
        batch = 2000
        made = {"users": 0, "bookings": 0, "checked_in": 0, "cancelled": 0, "reviews": 0}
        review_pairs = set(Review.objects.values_list("user_id", "museum_id"))
        for start in range(0, n, batch):
            size = min(batch, n - start)
            users = []
            for i in range(size):
                if (start + i) % 25 == 0:
                    first, last = self.rng.choice(FOREIGN)
                    persona = "foreign"
                else:
                    first, last = self.rng.choice(FIRST_NAMES), self.rng.choice(SURNAMES)
                    persona = self.rng.choice(["solo", "couple", "couple", "family", "family", "student"])
                joined = self.now - datetime.timedelta(days=self.rng.randint(1, 720), minutes=self.rng.randint(0, 1440))
                users.append(User(
                    email=self.email_for(first, last), first_name=first, last_name=last, phone=self.phone(),
                    password=hashed, role=User.Role.VISITOR, is_sample=True, date_joined=joined,
                    last_login=joined + datetime.timedelta(days=self.rng.randint(0, max(1, (self.now - joined).days)))
                    if self.rng.random() < 0.8 else None,
                ))
                users[-1].persona = persona
            personas = [u.persona for u in users]
            created = User.objects.bulk_create(users, batch_size=batch)
            made["users"] += len(created)

            bookings, lines, checks, reviews = [], [], [], []
            for user, persona in zip(created, personas):
                city = self.rng.choice(cities)
                self.mass_rows.append((user.get_full_name(), user.email, user.phone, city, user.date_joined))
                if self.rng.random() > 0.6:
                    continue
                for _ in range(self.rng.choices([1, 2, 3], [55, 30, 15])[0]):
                    museum = self.rng.choices(places, weights)[0]
                    data = info[museum.pk]
                    if not data["slots"] or not data["tickets"]:
                        continue
                    past = self.rng.random() < 0.6
                    day = self.today + datetime.timedelta(days=-self.rng.randint(1, 180) if past else self.rng.randint(1, 45))
                    slot = self.rng.choice(data["slots"])
                    if closed(museum, slot, day):
                        continue
                    mix = self.ticket_mix_from(data["tickets"], persona)
                    priced = [(t, q, services.effective_price(t, day, data["rules"])[0]) for t, q in mix]
                    total = sum((p * q for _, q, p in priced), Decimal("0"))
                    visitors = sum(q for _, q, _ in priced)
                    booked = self.moment(day, slot.start_time.hour) - datetime.timedelta(days=self.rng.randint(1, 25), hours=self.rng.randint(1, 12))
                    booked = min(booked, self.now - datetime.timedelta(minutes=self.rng.randint(5, 600)))
                    ref = generate_reference()
                    while ref in refs:
                        ref = generate_reference()
                    refs.add(ref)
                    r = self.rng.random()
                    status, cancelled_at, refund = Booking.Status.CONFIRMED, None, Decimal("0")
                    if r < 0.06:
                        status, cancelled_at, refund = Booking.Status.CANCELLED, booked + datetime.timedelta(hours=self.rng.randint(2, 30)), total
                    elif past and r < 0.92:
                        status = Booking.Status.CHECKED_IN
                    b = Booking(
                        reference=ref, user=user, museum=museum, slot=slot, visit_date=day, status=status,
                        channel=Booking.Channel.ONLINE, total_visitors=visitors, total_amount=total,
                        visitor_name=user.get_full_name(), visitor_email=user.email, visitor_phone=user.phone,
                        payment_method=self.rng.choice(["upi", "upi", "upi", "card", "netbanking", "wallet"]) if total else "free",
                        payment_id=f"pay_demo{self.rng.randrange(16**10):010x}" if total else "", gateway="mock" if total else "",
                        created_at=booked, paid_at=booked + datetime.timedelta(minutes=self.rng.randint(1, 6)),
                        cancelled_at=cancelled_at, refund_amount=refund,
                        refund_status=Booking.RefundStatus.PROCESSED if refund else "",
                        refund_id=f"rfnd_demo{self.rng.randrange(16**10):010x}" if refund else "",
                    )
                    if status == Booking.Status.CHECKED_IN:
                        arrived = self.moment(day, slot.start_time.hour, slot.start_time.minute) + datetime.timedelta(minutes=self.rng.randint(0, 45))
                        b.checked_in_at, b.visitors_arrived, b.checked_in_by = arrived, visitors, checkers[museum.pk]
                    bookings.append((b, priced))
            with self.keep_timestamps(Booking, Review):
                Booking.objects.bulk_create([b for b, _ in bookings], batch_size=batch)
                for b, priced in bookings:
                    for t, q, price in priced:
                        lines.append(BookingItem(booking=b, ticket_type=t, ticket_name=t.name, quantity=q, unit_price=price))
                    if b.status == Booking.Status.CHECKED_IN:
                        checks.append(GateScan(booking=b, admitted=b.total_visitors, scanned_at=b.checked_in_at, scanned_by=b.checked_in_by))
                        key = (b.user_id, b.museum_id)
                        if key not in review_pairs and self.rng.random() < 0.2:
                            review_pairs.add(key)
                            title, comment = self.rng.choice(REVIEWS.get(b.museum.place_type, REVIEWS["museum"]))
                            when = min(b.checked_in_at + datetime.timedelta(days=self.rng.randint(0, 3), hours=5), self.now)
                            reviews.append(Review(museum=b.museum, user=b.user, rating=self.rng.choice(RATINGS), title=title,
                                                  comment=comment, created_at=when, updated_at=when))
                BookingItem.objects.bulk_create(lines, batch_size=batch)
                GateScan.objects.bulk_create(checks, batch_size=batch)
                Review.objects.bulk_create(reviews, batch_size=batch)
            made["bookings"] += len(bookings)
            made["checked_in"] += len(checks)
            made["cancelled"] += sum(1 for b, _ in bookings if b.status == Booking.Status.CANCELLED)
            made["reviews"] += len(reviews)
            self.stdout.write(f"  mass: {start + size}/{n} users, {made['bookings']} bookings so far")
        for key, value in made.items():
            self.count(f"mass {key}", value)

    def ticket_mix_from(self, types, persona):
        def find(*words):
            return next((t for t in types if any(w in t.name.lower() for w in words)), None)

        adult = find("indian", "adult") or types[0]
        child, student, foreign = find("child"), find("student"), find("foreign")
        if persona == "family":
            mix = [(adult, 2)] + ([(child, self.rng.randint(1, 2))] if child else [])
        elif persona == "student":
            mix = [(student or adult, self.rng.randint(1, 3))]
        elif persona == "couple":
            mix = [(adult, 2)]
        elif persona == "foreign" and foreign:
            mix = [(foreign, self.rng.randint(1, 3))]
        else:
            mix = [(adult, self.rng.randint(1, 2))]
        return [(t, q) for t, q in mix if t]

    def append_visitors(self):
        """--append: add visitors (and their bookings/reviews) next to the existing data; nothing is deleted."""
        self.logins = []
        self.used_emails = set(User.objects.values_list("email", flat=True))
        self.used_phones = set(User.objects.exclude(phone="").values_list("phone", flat=True))
        self.admin = User.objects.get(email="admin@ancientantiquity.in")
        self.staff = (User.objects.filter(role=User.Role.STAFF, is_sample=True).first()
                      or User.objects.get(email="staff@ancientantiquity.in"))
        places = self.places()
        featured = [p for p in places if p.is_featured] or places
        self.bulk_password = self.existing_shared_password()
        with transaction.atomic():
            self.seed_bulk_visitors(self.bulk_count, places, featured)
        self.seed_mass(self.mass_count, places, featured)
        self.seed_mass_bookings(self.mass_bookings, places)

    def seed_mass_bookings(self, n, places):
        """Add `n` bookings (with ticket lines, check-ins, refunds, reviews) over the existing sample visitors,
        plus favourites and support messages. Batches of 20,000, each committed on its own."""
        from bookings import services
        from bookings.models import Booking, BookingItem, GateScan, generate_reference
        from museums.models import PriceRule, Review
        from support.models import ContactMessage
        from trips.models import Favourite

        if n <= 0:
            return
        people = list(User.objects.filter(is_sample=True, role=User.Role.VISITOR)
                      .values_list("id", "first_name", "last_name", "email", "phone"))
        if not people:
            raise CommandError("No sample visitors to give bookings to; run with --users/--mass-users first.")
        weights = [8 if p.is_featured else 1 for p in places]
        info = {p.pk: {"museum": p,
                       "slots": list(p.slots.filter(is_active=True).order_by("start_time")),
                       "tickets": list(p.ticket_types.filter(is_active=True).order_by("sort_order", "id")),
                       "rules": list(PriceRule.objects.filter(museum=p, is_active=True).order_by("-priority", "-id"))}
                for p in places}
        bookable = [p for p in places if info[p.pk]["slots"] and info[p.pk]["tickets"]]
        weights = [8 if p.is_featured else 1 for p in bookable]
        checkers = {p.pk: (self.staff.pk if p in self.staff.assigned_museums.all() else self.admin.pk) for p in bookable}
        closure_cache = {}
        refs = set(Booking.objects.values_list("reference", flat=True))
        review_pairs = set(Review.objects.values_list("user_id", "museum_id"))
        extras = REVIEW_EXTRAS
        batch = 20000
        made = {"bookings": 0, "checked_in": 0, "cancelled": 0, "reviews": 0}
        for start in range(0, n, batch):
            rows = []
            for _ in range(min(batch, n - start)):
                uid, first, last, email, phone = self.rng.choice(people)
                museum = self.rng.choices(bookable, weights)[0]
                data = info[museum.pk]
                past = self.rng.random() < 0.8
                day = self.today + datetime.timedelta(days=-self.rng.randint(1, 365) if past else self.rng.randint(1, 60))
                slot = self.rng.choice(data["slots"])
                key = (museum.pk, day)
                if key not in closure_cache:
                    closure_cache[key] = museum.closure_on(day)
                if closure_cache[key]["closed"] or slot.id in closure_cache[key]["slots"]:
                    continue
                persona = "foreign" if self.rng.random() < 0.04 else self.rng.choice(["solo", "couple", "couple", "family", "family", "student"])
                priced = [(t, q, services.effective_price(t, day, data["rules"])[0]) for t, q in self.ticket_mix_from(data["tickets"], persona)]
                if not priced:
                    continue
                total = sum((pr * q for _, q, pr in priced), Decimal("0"))
                visitors = sum(q for _, q, _ in priced)
                booked = self.moment(day, slot.start_time.hour) - datetime.timedelta(days=self.rng.randint(0, 25), hours=self.rng.randint(1, 12))
                booked = min(booked, self.now - datetime.timedelta(minutes=self.rng.randint(5, 600)))
                ref = generate_reference()
                while ref in refs:
                    ref = generate_reference()
                refs.add(ref)
                r = self.rng.random()
                status, cancelled_at, refund = Booking.Status.CONFIRMED, None, Decimal("0")
                if r < 0.06:
                    status, cancelled_at, refund = Booking.Status.CANCELLED, booked + datetime.timedelta(hours=self.rng.randint(2, 30)), total
                elif past and r < 0.92:
                    status = Booking.Status.CHECKED_IN
                name = f"{first} {last}"
                b = Booking(
                    reference=ref, user_id=uid, museum_id=museum.pk, slot_id=slot.pk, visit_date=day, status=status,
                    channel=Booking.Channel.ONLINE, total_visitors=visitors, total_amount=total, visitor_name=name,
                    visitor_email=email, visitor_phone=phone,
                    payment_method=self.rng.choice(["upi", "upi", "upi", "card", "netbanking", "wallet"]) if total else "free",
                    payment_id=f"pay_demo{self.rng.randrange(16**10):010x}" if total else "", gateway="mock" if total else "",
                    created_at=booked, paid_at=booked + datetime.timedelta(minutes=self.rng.randint(1, 6)),
                    cancelled_at=cancelled_at, refund_amount=refund,
                    refund_status=Booking.RefundStatus.PROCESSED if refund else "",
                    refund_id=f"rfnd_demo{self.rng.randrange(16**10):010x}" if refund else "",
                )
                if status == Booking.Status.CHECKED_IN:
                    b.checked_in_at = self.moment(day, slot.start_time.hour, slot.start_time.minute) + datetime.timedelta(minutes=self.rng.randint(0, 45))
                    b.visitors_arrived, b.checked_in_by_id = visitors, checkers[museum.pk]
                rows.append((b, priced, museum))
            lines, scans, reviews = [], [], []
            with transaction.atomic(), self.keep_timestamps(Booking, Review):
                Booking.objects.bulk_create([b for b, _, _ in rows], batch_size=5000)
                for b, priced, museum in rows:
                    for t, q, price in priced:
                        lines.append(BookingItem(booking_id=b.pk, ticket_type_id=t.pk, ticket_name=t.name, quantity=q, unit_price=price))
                    if b.status == Booking.Status.CHECKED_IN:
                        scans.append(GateScan(booking_id=b.pk, admitted=b.total_visitors, scanned_at=b.checked_in_at,
                                              scanned_by_id=b.checked_in_by_id))
                        pair = (b.user_id, museum.pk)
                        if pair not in review_pairs and self.rng.random() < 0.15:
                            review_pairs.add(pair)
                            title, comment = self.rng.choice(REVIEWS.get(museum.place_type, REVIEWS["museum"]))
                            if self.rng.random() < 0.6:
                                comment = f"{comment} {self.rng.choice(extras)}"
                            when = min(b.checked_in_at + datetime.timedelta(days=self.rng.randint(0, 4), hours=5), self.now)
                            reviews.append(Review(museum_id=museum.pk, user_id=b.user_id, rating=self.rng.choice(RATINGS),
                                                  title=title, comment=comment, created_at=when, updated_at=when))
                BookingItem.objects.bulk_create(lines, batch_size=5000)
                GateScan.objects.bulk_create(scans, batch_size=5000)
                Review.objects.bulk_create(reviews, batch_size=5000)
            made["bookings"] += len(rows)
            made["checked_in"] += len(scans)
            made["cancelled"] += sum(1 for b, _, _ in rows if b.status == Booking.Status.CANCELLED)
            made["reviews"] += len(reviews)
            self.stdout.write(f"  {min(start + batch, n):,}/{n:,} attempted - {made['bookings']:,} bookings saved", ending="\n")
            self.stdout.flush()

        # Favourites and support messages, in proportion.
        favs = []
        for uid, *_ in self.rng.sample(people, min(len(people), len(people) * 2 // 5)):
            for museum in self.rng.sample(bookable, min(len(bookable), self.rng.randint(1, 5))):
                favs.append(Favourite(user_id=uid, museum_id=museum.pk))
        Favourite.objects.bulk_create(favs, batch_size=5000, ignore_conflicts=True)
        topics = [("booking", "Can I change the visit date of my booking {ref}?", "closed"),
                  ("refund", "When will the refund for {ref} reach my account?", "closed"),
                  ("group", "Do you offer guided tours for a group of 40 students?", "new"),
                  ("data", "The closing time shown for this place seems wrong.", "in_progress"),
                  ("other", "Is photography allowed inside the galleries?", "closed")]
        msgs = []
        recent = list(Booking.objects.filter(user__is_sample=True).order_by("-id").values_list("reference", flat=True)[:5000])
        for uid, first, last, email, phone in self.rng.sample(people, min(len(people), 1500)):
            topic, text, status = self.rng.choice(topics)
            when = self.now - datetime.timedelta(days=self.rng.randint(0, 200), minutes=self.rng.randint(0, 1440))
            msgs.append(ContactMessage(user_id=uid, name=f"{first} {last}", email=email, phone=phone, topic=topic,
                                       message=text.format(ref=self.rng.choice(recent) if recent else ""), status=status,
                                       created_at=when, updated_at=when))
        with self.keep_timestamps(ContactMessage):
            ContactMessage.objects.bulk_create(msgs, batch_size=5000)
        for key, value in made.items():
            self.count(f"added {key}", value)
        self.count("added favourites", len(favs))
        self.count("added support messages", len(msgs))

    def existing_shared_password(self):
        """Reuse the shared sample password from LOGIN_DETAILS.md so old and new sample visitors sign in alike."""
        import re

        path = Path(settings.BASE_DIR).parent / "docs" / "LOGIN_DETAILS.md"
        text = path.read_text(encoding="utf-8") if path.exists() else ""
        m = re.search(r"signs in with the password `([^`]+)`", text)
        return m.group(1) if m else ""

    def append_csv(self):
        import csv

        if not (self.bulk_users or self.mass_rows):
            return  # no new people: leave sample-users.csv exactly as it is

        path = Path(settings.BASE_DIR).parent / "docs" / "sample-users.csv"
        new = not path.exists()
        with open(path, "a", newline="", encoding="utf-8-sig" if new else "utf-8") as f:
            writer = csv.writer(f)
            if new:
                writer.writerow(["name", "email", "phone", "city", "joined"])
            for u in self.bulk_users:
                writer.writerow([u.get_full_name(), u.email, u.phone, u.home_city, f"{timezone.localtime(u.date_joined):%Y-%m-%d}"])
            for name, email, phone, city, joined in self.mass_rows:
                writer.writerow([name, email, phone, city, f"{timezone.localtime(joined):%Y-%m-%d}"])
        self.stdout.write(f"Added {len(self.bulk_users) + len(self.mass_rows):,} rows to {path} "
                          f"(shared password unchanged: see LOGIN_DETAILS.md)")

    def state_of(self, city_name):
        from museums.models import City

        return {c.state.name for c in City.objects.filter(name=city_name).select_related("state")}

    # ------------------------------------------------------------------ promotions

    def seed_promotions(self, places):
        from promotions.models import GiftVoucher, PromoCode

        year = self.today.year
        tz = timezone.get_current_timezone()
        start = timezone.make_aware(datetime.datetime(year, 1, 1), tz)
        self.promos = {
            "WELCOME10": PromoCode.objects.create(
                code="WELCOME10", description="10% off your first booking (up to ₹100)", value=10, max_discount=100,
                first_booking_only=True, per_user_limit=1, valid_from=start, created_by=self.admin),
            "MONUMENTS50": PromoCode.objects.create(
                code="MONUMENTS50", description="₹50 off forts, palaces and monuments on orders of ₹300+",
                discount_type=PromoCode.DiscountType.FLAT, value=50, min_order_amount=300, scope=PromoCode.Scope.PLACE_TYPES,
                place_types="fort,palace,monument", per_user_limit=3, valid_from=start, created_by=self.admin),
            "HERITAGEWEEK": PromoCode.objects.create(
                code="HERITAGEWEEK", description="World Heritage Week: 20% off (19–25 November)", value=20, max_discount=250,
                valid_from=timezone.make_aware(datetime.datetime(year, 11, 19), tz),
                valid_to=timezone.make_aware(datetime.datetime(year, 11, 25, 23, 59), tz), per_user_limit=2, created_by=self.admin),
            "SCHOOLTRIP": PromoCode.objects.create(
                code="SCHOOLTRIP", description="Extra 10% for school and college groups", value=10,
                applies_to=PromoCode.AppliesTo.GROUP, per_user_limit=None, valid_from=start, created_by=self.admin),
        }
        for name, email, value in (("Aditi Rao", self.email_for("Aditi", "Rao"), 1000), ("Corporate gifting - Tata Elxsi", self.email_for("hr", "gifting"), 2500)):
            GiftVoucher.objects.create(initial_value=value, balance=value, purchaser_name=name, purchaser_email=email,
                                       recipient_name=name.split(" - ")[0], recipient_email=email,
                                       message="Happy exploring India's heritage!", issued_by=self.admin)
        self.count("promo codes", len(self.promos))
        self.count("gift vouchers", 2)

    # ------------------------------------------------------------------ memberships

    def seed_memberships(self, visitors):
        from memberships import services as membership_services
        from memberships.models import MembershipPlan

        plans = {p.slug: p for p in MembershipPlan.objects.filter(is_active=True)}
        if not plans:
            return
        family = next((p for p in plans.values() if "family" in p.slug), None)
        individual = next((p for p in plans.values() if "individual" in p.slug), None) or next(iter(plans.values()))
        student = next((p for p in plans.values() if "student" in p.slug), None)
        for user in visitors:
            if user.persona != "member":
                continue
            plan = family if user.first_name == "Ishaan" and family else individual
            with self.at(self.now - datetime.timedelta(days=self.rng.randint(80, 110), hours=3)):
                m = membership_services.create_membership(user=user, plan=plan, holder_name=user.get_full_name())
                membership_services.confirm_payment(m, "upi", payment_id=f"pay_demo{secrets.token_hex(5)}")
            self.notes_for(user, f"Heritage Card member ({plan.name})")
            self.count("Heritage Cards")
        ananya = next((u for u in visitors if u.first_name == "Ananya"), None)
        if ananya and student:
            with self.at(self.now - datetime.timedelta(days=40)):
                m = membership_services.create_membership(user=ananya, plan=student, holder_name=ananya.get_full_name())
                membership_services.confirm_payment(m, "upi", payment_id=f"pay_demo{secrets.token_hex(5)}")
            self.notes_for(ananya, f"Heritage Card member ({student.name})")
            self.count("Heritage Cards")

    def notes_for(self, user, text):
        for row in self.logins:
            if row["email"] == user.email:
                row["notes"] = f"{row['notes']}; {text}" if row["notes"] else text

    # ------------------------------------------------------------------ bookings

    def online_booking(self, user, museum, *, past, persona=None):
        from addons.models import AddOn
        from bookings import services
        from bookings.models import Booking
        from promotions import services as promo_services

        persona = persona or getattr(user, "persona", "solo")
        if past:
            visit = self.open_visit(museum, self.today - datetime.timedelta(days=120), self.today - datetime.timedelta(days=1))
        else:
            visit = self.open_visit(museum, self.today + datetime.timedelta(days=1), self.today + datetime.timedelta(days=45))
        if not visit:
            return None
        day, slot = visit
        items = self.ticket_mix(museum, persona)
        if not items:
            return None
        if past:
            booked_at = self.moment(day - datetime.timedelta(days=self.rng.randint(1, 20)), self.rng.randint(8, 22), self.rng.choice((5, 20, 35, 50)))
        else:
            booked_at = self.now - datetime.timedelta(days=self.rng.randint(0, 12), hours=self.rng.randint(1, 10))
        method = self.rng.choice(("upi", "upi", "upi", "card", "netbanking", "wallet"))
        try:
            with self.at(booked_at):
                booking = services.create_booking(
                    user=user, museum=museum, slot=slot, visit_date=day, items=items,
                    visitor_name=user.get_full_name(), visitor_email=user.email, visitor_phone=user.phone,
                )
                addons = list(AddOn.objects.filter(museum=museum, is_active=True))
                if addons and self.rng.random() < 0.4:
                    pick = self.rng.choice(addons)
                    qty = booking.total_visitors if pick.per == "person" and not pick.price == 0 else 1
                    if pick.max_per_booking:
                        qty = min(qty, pick.max_per_booking)
                    with contextlib.suppress(ValidationError, DjangoValidationError):
                        services.set_booking_addons(booking, [{"addon": pick.id, "quantity": qty}])
                        self.count("bookings with add-ons")
                booking.refresh_from_db()
                first_booking = not Booking.objects.filter(user=user).exclude(pk=booking.pk).exists()
                if booking.status == Booking.Status.PENDING and (first_booking and self.rng.random() < 0.5 or self.rng.random() < 0.2):
                    code = "WELCOME10" if first_booking else self.rng.choice(["MONUMENTS50", "HERITAGEWEEK"])
                    with contextlib.suppress(ValidationError, DjangoValidationError):
                        promo_services.apply_code(booking, code)
                        self.count(f"promo {code} used")
                booking.refresh_from_db()
                if booking.status == Booking.Status.PENDING:
                    services.confirm_payment(booking, method, payment_id=f"pay_demo{secrets.token_hex(6)}")
        except (ValidationError, DjangoValidationError) as exc:
            self.skipped.append(f"{museum.name} {day}: {exc}")
            return None
        booking.refresh_from_db()
        self.count("online bookings")
        if past:
            r = self.rng.random()
            if r < 0.1:
                with self.at(booked_at + datetime.timedelta(hours=self.rng.randint(2, 30))):
                    if self.moment(day, slot.start_time.hour) > timezone.now():
                        services.cancel_booking(booking)
                        self.count("cancelled + refunded")
            elif r < 0.17:
                self.count("no-shows")
            else:
                arrive = self.moment(day, slot.start_time.hour, slot.start_time.minute) + datetime.timedelta(minutes=self.rng.randint(0, 40))
                with self.at(arrive):
                    services.mark_checked_in(booking, self.staff if museum in self.staff.assigned_museums.all() else self.admin)
                self.count("checked-in visits")
        return booking

    def seed_counter_sales(self, places):
        from bookings import services
        from bookings.models import Booking

        for i in range(16):
            museum = self.rng.choice(places)
            visit = self.open_visit(museum, self.today - datetime.timedelta(days=30), self.today)
            if not visit:
                continue
            day, slot = visit
            sold_at = self.moment(day, slot.start_time.hour, 5) - datetime.timedelta(minutes=self.rng.randint(5, 50))
            name = WALK_IN_NAMES[i % len(WALK_IN_NAMES)]
            items = self.ticket_mix(museum, "foreign" if name in ("John Miller", "Emma Schmidt") else self.rng.choice(["family", "couple", "solo"]))
            if name in ("John Miller", "Emma Schmidt"):
                foreign = museum.ticket_types.filter(is_active=True, name__icontains="foreign").first()
                items = [{"ticket_type": foreign, "quantity": 1}] if foreign else items
            try:
                with self.at(sold_at):
                    services.create_booking(
                        user=self.staff, museum=museum, slot=slot, visit_date=day, items=items, visitor_name=name,
                        channel=Booking.Channel.COUNTER, payment_method=self.rng.choice(["cash", "cash", "upi", "card"]),
                        check_in=True,
                    )
                self.count("ticket counter sales")
            except (ValidationError, DjangoValidationError) as exc:
                self.skipped.append(f"counter {museum.name}: {exc}")

    def seed_groups(self, places):
        from bookings import services
        from bookings.models import Booking

        groups = [
            # Sized to fit a slot's group share (30 people); bigger parties go through group requests.
            ("school", "Delhi Public School, Bopal", 24, 2, "Ahmedabad"),
            ("college", "St. Xavier's College History Club", 22, 2, "Mumbai"),
            ("corporate", "Infosys Mysuru - Team outing", 26, 0, "Mysuru"),
        ]
        for group_type, org, people, escorts, _city in groups:
            museum = self.rng.choice([p for p in places if p.allow_groups] or places)
            visit = self.open_visit(museum, self.today - datetime.timedelta(days=60), self.today + datetime.timedelta(days=30))
            if not visit:
                continue
            day, slot = visit
            ticket = services.default_group_ticket_type(museum)
            leader = self.rng.choice(self.logins)
            user = User.objects.get(email=leader["email"])
            try:
                booked = min(self.moment(day, 9) - datetime.timedelta(days=14), self.now - datetime.timedelta(hours=5))
                with self.at(booked):
                    booking = services.create_booking(
                        user=user, museum=museum, slot=slot, visit_date=day, items=[{"ticket_type": ticket, "quantity": people}],
                        visitor_name=user.get_full_name(), visitor_email=user.email, visitor_phone=user.phone,
                        group_type=group_type, organisation_name=org, escort_count=escorts,
                    )
                    if booking.status == Booking.Status.PENDING:
                        services.confirm_payment(booking, "netbanking", payment_id=f"pay_demo{secrets.token_hex(6)}")
                if day < self.today:
                    with self.at(self.moment(day, slot.start_time.hour, 10)):
                        services.mark_checked_in(booking, self.admin)
                self.count("group bookings")
            except (ValidationError, DjangoValidationError) as exc:
                self.skipped.append(f"group {org}: {exc}")

    def seed_group_requests(self, visitors, places):
        """Large groups (61+) ask for a quote; staff decide. Approval allocates real slots, so leave that to staff."""
        from grouprequests.models import GroupRequest

        rows = [
            ("school", "Kendriya Vidyalaya No. 2, Jaipur", 120, 8, True, GroupRequest.Status.SUBMITTED, ""),
            ("college", "Presidency University Heritage Club", 75, 4, True, GroupRequest.Status.UNDER_REVIEW,
             "Checking guide availability for Bengali."),
            ("corporate", "Wipro Pune - annual offsite", 90, 0, False, GroupRequest.Status.DECLINED,
             "Requested date falls in the Diwali week when the place is at capacity; suggested 18 Nov instead."),
        ]
        for (group_type, org, people, escorts, guide, status, note), user in zip(rows, self.rng.sample(visitors, min(len(rows), len(visitors)))):
            museum = self.rng.choice([p for p in places if p.allow_groups] or places)
            visit = self.open_visit(museum, self.today + datetime.timedelta(days=12), self.today + datetime.timedelta(days=50))
            if not visit:
                continue
            day, slot = visit
            alt = self.open_visit(museum, day + datetime.timedelta(days=2), day + datetime.timedelta(days=9))
            with self.at(self.now - datetime.timedelta(days=self.rng.randint(1, 9), hours=self.rng.randint(1, 6))):
                GroupRequest.objects.create(
                    requester=user, museum=museum, preferred_date=day, alternative_date=alt[0] if alt else None,
                    preferred_time=self.rng.choice(["morning", "afternoon", "any"]), group_type=group_type,
                    organisation_name=org, contact_name=user.get_full_name(), contact_email=user.email,
                    contact_phone=user.phone, participants=people, escorts=escorts, needs_guide=guide,
                    notes="Two students use wheelchairs." if group_type == "school" else "",
                    status=status, staff_notes=note,
                    decided_by=self.admin if status == GroupRequest.Status.DECLINED else None,
                    decided_at=timezone.now() if status == GroupRequest.Status.DECLINED else None,
                )
            self.count("group requests")

    def seed_agent(self):
        from partners.models import AgentProfile

        first, last, city, company = AGENT_PERSON
        user = self.make_user(first, last, city, role=User.Role.AGENT, word="Operator")
        profile = AgentProfile.objects.create(
            user=user, company_name=company, gstin="08AAICI1234F1Z9", contact_phone=user.phone, city=city,
            message="Rajasthan and Golden Triangle tours for families and small groups since 2012.",
            commission_percent=Decimal("10.00"), credit_limit=Decimal("50000.00"),
            status=AgentProfile.Status.APPROVED, is_approved=True, approved_by=self.admin, approved_at=self.now,
        )
        self.logins[-1]["notes"] = f"Tour operator ({company}), books on account at /agent; GSTIN is a SAMPLE"
        return profile

    def seed_kiosk(self, places):
        """A self-service ticket kiosk at the first staff place (signs in at /kiosk)."""
        from partners.models import KioskDevice

        if not places:
            return
        user = self.make_user("Kiosk", places[0].name.split(" ")[0], places[0].city.name, role=User.Role.KIOSK,
                              word="Kiosk", domain="ancientantiquity.in")
        device = KioskDevice.objects.create(user=user, name=f"{places[0].name} gate kiosk", created_by=self.admin)
        device.museums.add(places[0])
        self.logins[-1]["notes"] = f"Self-service kiosk for {places[0].name}: sign in at /kiosk"

    def seed_agent_bookings(self, profile, places):
        from bookings import services
        from bookings.models import Booking
        from partners import services as partner_services

        rajasthan = [p for p in places if p.city.state.name == "Rajasthan"] or places
        for i in range(4):
            museum = self.rng.choice(rajasthan)
            visit = self.open_visit(museum, self.today - datetime.timedelta(days=40), self.today + datetime.timedelta(days=20))
            if not visit:
                continue
            day, slot = visit
            items = self.ticket_mix(museum, self.rng.choice(["family", "couple"]))
            guest = ["The Wilson family", "Mr & Mrs Kapoor", "Sato family", "Mr & Mrs Fernandes"][i]
            try:
                with self.at(min(self.moment(day, 9) - datetime.timedelta(days=7), self.now - datetime.timedelta(hours=3))):
                    booking = services.create_booking(
                        user=profile.user, museum=museum, slot=slot, visit_date=day, items=items, visitor_name=guest,
                        visitor_email=profile.user.email, visitor_phone=profile.contact_phone,
                        channel=Booking.Channel.AGENT, payment_method="bank_transfer",
                    )
                    if booking.status == Booking.Status.PENDING:
                        services.confirm_payment(booking, "bank_transfer")
                self.count("tour operator bookings")
            except (ValidationError, DjangoValidationError) as exc:
                self.skipped.append(f"agent {museum.name}: {exc}")
        partner_services.recalc_balance(profile)

    def seed_events(self, visitors):
        from bookings import services
        from bookings.models import Booking
        from events import services as event_services
        from events.models import EventSession

        sessions = list(EventSession.objects.filter(date__gte=self.today, date__lte=self.today + datetime.timedelta(days=25))
                        .select_related("event"))
        self.rng.shuffle(sessions)
        for user, session in zip(self.rng.sample(visitors, min(7, len(visitors))), sessions):
            price = session.event.prices.order_by("sort").first()
            if not price:
                continue
            try:
                with self.at(self.now - datetime.timedelta(days=self.rng.randint(0, 6), hours=2)):
                    booking = event_services.create_event_booking(
                        user=user, session=session, items=[{"price": price, "quantity": self.rng.randint(2, 4)}],
                        visitor_name=user.get_full_name(), visitor_email=user.email, visitor_phone=user.phone)
                    if booking.status == Booking.Status.PENDING:
                        services.confirm_payment(booking, "upi", payment_id=f"pay_demo{secrets.token_hex(6)}")
                self.count("event tickets")
            except (ValidationError, DjangoValidationError) as exc:
                self.skipped.append(f"event {session}: {exc}")

    def seed_passes(self, visitors):
        from passes import services as pass_services
        from passes.models import ComboPass, PassOrder

        passes = list(ComboPass.objects.filter(is_active=True))
        for user in self.rng.sample(visitors, min(3, len(visitors))):
            if not passes:
                break
            combo = self.rng.choice(passes)
            start = self.today + datetime.timedelta(days=self.rng.randint(3, 30))
            try:
                with self.at(self.now - datetime.timedelta(days=self.rng.randint(0, 5))):
                    order = pass_services.create_order(user=user, combo_pass=combo, start_date=start, counts={"indian": 2},
                                                       visitor_name=user.get_full_name(), visitor_email=user.email,
                                                       visitor_phone=user.phone)
                    if order.status == PassOrder.Status.PENDING:
                        pass_services.confirm_payment(order, "upi", payment_id=f"pay_demo{secrets.token_hex(6)}")
                self.count("combo pass orders")
            except (ValidationError, DjangoValidationError) as exc:
                self.skipped.append(f"pass {combo}: {exc}")

    # ------------------------------------------------------------------ reviews

    def seed_reviews(self):
        from bookings.models import Booking
        from museums.models import Review

        visits = (Booking.objects.filter(status=Booking.Status.CHECKED_IN, channel=Booking.Channel.ONLINE, is_group=False)
                  .exclude(user__email__in=KEEP_EMAILS[:2]).select_related("museum", "user").order_by("visit_date"))
        seen = set()
        for b in visits:
            key = (b.user_id, b.museum_id)
            if key in seen or self.rng.random() > 0.7:
                continue
            seen.add(key)
            title, comment = self.rng.choice(REVIEWS.get(b.museum.place_type, REVIEWS["museum"]))
            when = self.moment(b.visit_date + datetime.timedelta(days=self.rng.randint(0, 3)), self.rng.randint(18, 22))
            with self.at(min(when, self.now)):
                Review.objects.create(museum=b.museum, user=b.user, rating=self.rng.choice(RATINGS), title=title, comment=comment)
            self.count("reviews")

    # ------------------------------------------------------------------ donations

    def seed_donations(self, visitors, places):
        from donations import services as donation_services
        from donations.models import Donation

        gifts = [(1000, True), (2500, True), (500, False), (5000, True), (1500, False), (750, False)]
        for (amount, wants_80g), user in zip(gifts, self.rng.sample(visitors, min(len(gifts), len(visitors)))):
            museum = self.rng.choice(places) if self.rng.random() < 0.6 else None
            with self.at(self.now - datetime.timedelta(days=self.rng.randint(1, 80), hours=self.rng.randint(1, 9))):
                d = Donation.objects.create(
                    user=user, museum=museum, donor_name=user.get_full_name(), donor_email=user.email, donor_phone=user.phone,
                    donor_pan=self.pan(user.last_name) if wants_80g else "",
                    donor_address=f"{self.rng.randint(4, 220)}, {self.rng.choice(['MG Road', 'Station Road', 'Lake View Society', 'Gandhi Nagar'])}, {user.home_city}" if wants_80g else "",
                    amount=Decimal(amount), wants_80g=wants_80g,
                )
                donation_services.mark_paid(d, "upi", payment_id=f"pay_demo{secrets.token_hex(6)}")
            self.count("donations")
            if wants_80g:
                self.notes_for(user, "donated with an 80G receipt (sample PAN)")

    # ------------------------------------------------------------------ favourites, trips, support, waitlist

    def seed_favourites_and_trips(self, visitors, places):
        from trips.models import Favourite, Trip, TripStop

        for user in visitors:
            for museum in self.rng.sample(places, min(len(places), self.rng.randint(2, 6))):
                Favourite.objects.get_or_create(user=user, museum=museum)
                self.count("favourites")
        plans = [
            ("Priya", "Jaipur weekend", "Rajasthan", 2),
            ("Rohan", "Golden Triangle with parents", None, 4),
            ("Meera", "Hampi & Mysuru", "Karnataka", 3),
            ("Kabir", "Delhi heritage walk", "Delhi", 2),
        ]
        for first, title, state, days in plans:
            user = next((u for u in visitors if u.first_name == first), None)
            if not user:
                continue
            if state:
                pool = [p for p in places if p.city.state.name == state]
            else:
                pool = [p for p in places if p.city.name in ("New Delhi", "Agra", "Jaipur")]
            if len(pool) < 2:
                continue
            start = self.today + datetime.timedelta(days=self.rng.randint(10, 40))
            trip = Trip.objects.create(user=user, title=title, start_date=start, end_date=start + datetime.timedelta(days=days - 1),
                                       notes="Book the morning slots; carry water and comfortable shoes.")
            stops = self.rng.sample(pool, min(len(pool), days * 2))
            for i, museum in enumerate(stops):
                TripStop.objects.create(trip=trip, museum=museum, day=i // 2 + 1, order=i % 2,
                                        planned_time=datetime.time(9 if i % 2 == 0 else 14, 30))
            self.count("trip plans")

    def seed_support(self, visitors):
        from support.models import ContactMessage

        rows = [
            ("booking", "I booked the 10 am slot but my parents can only reach by 11. Can I change the slot?", "closed",
             "Moved to the 11:00 slot; confirmed by phone."),
            ("refund", "My refund for a cancelled booking hasn't reached my bank account yet.", "in_progress",
             "Refund processed on our side; bank takes 5-7 working days."),
            ("group", "We are 60 students from a school in Surat. Do you offer guides in Gujarati?", "new", ""),
            ("data", "The opening time on the website says 9:30 but the gate opened at 10 today.", "new", ""),
            ("partnership", "We run a private museum in Bhuj and would like to sell tickets on your platform.", "in_progress",
             "Sent partner onboarding form."),
        ]
        for (topic, message, status, note), user in zip(rows, self.rng.sample(visitors, min(len(rows), len(visitors)))):
            with self.at(self.now - datetime.timedelta(days=self.rng.randint(0, 25), hours=self.rng.randint(1, 8))):
                ContactMessage.objects.create(name=user.get_full_name(), email=user.email, phone=user.phone, topic=topic,
                                              message=message, status=status, admin_note=note, user=user)
            self.count("support messages")

    def seed_waitlist(self, visitors):
        from events.models import EventSession, WaitlistEntry

        sessions = list(EventSession.objects.filter(date__gt=self.today).order_by("date")[:2])
        for user, session in zip(self.rng.sample(visitors, min(2, len(visitors))), sessions):
            WaitlistEntry.objects.create(user=user, museum=session.event.museum, event_session=session,
                                         visit_date=session.date, quantity=2, notify_channels=["email"])
            self.count("waitlist entries")

    def seed_schools(self, visitors, places):
        """Uses the schools app's own seeder when it exists (batch C)."""
        from django.core.management import call_command, get_commands

        if "seed_schools" not in get_commands():
            return
        teachers = [u for u in visitors if u.first_name in ("Aarav", "Fatima")]
        try:
            call_command("seed_schools", users=",".join(u.email for u in teachers), stdout=self.stdout)
            self.count("school seed run")
            from schools.models import School

            for school in School.objects.filter(owner__in=teachers):
                state = "verified school" if school.status == "verified" else "school awaiting admin verification"
                self.notes_for(school.owner, f"Teacher: {state} ({school.name}) at /schools")
        except Exception as exc:  # the schools seeder is optional sample data
            self.skipped.append(f"schools: {exc}")

    # ------------------------------------------------------------------ analytics

    def seed_funnel(self, places):
        from analytics.models import FunnelEvent
        from bookings.models import Booking

        def session():
            return secrets.token_hex(12)

        steps = ["view_place", "select_slot", "start_booking", "view_checkout", "payment_started", "paid"]
        for b in Booking.objects.filter(channel=Booking.Channel.ONLINE).select_related("museum"):
            sid, t = session(), b.created_at - datetime.timedelta(minutes=self.rng.randint(4, 15))
            for i, step in enumerate(steps):
                with self.at(t + datetime.timedelta(minutes=i * 2)):
                    FunnelEvent.objects.create(session_id=sid, user=b.user, event=step, museum=b.museum,
                                               booking=b if i >= 2 else None)
        # Visitors who browsed but didn't book (the top of every real funnel is much wider).
        for _ in range(420):
            museum = self.rng.choice(places)
            sid = session()
            t = self.now - datetime.timedelta(days=self.rng.randint(0, 120), minutes=self.rng.randint(0, 1440))
            depth = self.rng.choices([1, 2, 3, 4], weights=[60, 22, 12, 6])[0]
            for i, step in enumerate(steps[:depth]):
                with self.at(t + datetime.timedelta(minutes=i * 2)):
                    FunnelEvent.objects.create(session_id=sid, event=step, museum=museum)
        self.count("funnel events", FunnelEvent.objects.count())

    def seed_settlements(self):
        from partners import services as partner_services

        first = (self.today.replace(day=1) - datetime.timedelta(days=1)).replace(day=1)
        last = self.today.replace(day=1) - datetime.timedelta(days=1)
        try:
            result = partner_services.generate_settlements(start=first, end=last, by=self.admin)
            self.count("settlement drafts", len(result) if hasattr(result, "__len__") else 1)
        except Exception as exc:
            self.skipped.append(f"settlements: {exc}")

    # ------------------------------------------------------------------ output

    def write_login_details(self):
        path = Path(settings.BASE_DIR).parent / "docs" / "LOGIN_DETAILS.md"
        start, end = "<!-- sample-users:start -->", "<!-- sample-users:end -->"
        rows = ["| Name | Email | Password | Role | City | Notes |", "|---|---|---|---|---|---|"]
        for r in self.logins:
            rows.append(f"| {r['name']} | `{r['email']}` | `{r['password']}` | {r['role']} | {r['city']} | {r['notes']} |")
        csv_path = path.with_name("sample-users.csv")
        if self.bulk_users or self.mass_rows:
            import csv

            with open(csv_path, "w", newline="", encoding="utf-8-sig") as f:
                writer = csv.writer(f)
                writer.writerow(["name", "email", "phone", "city", "joined"])
                for u in self.bulk_users:
                    writer.writerow([u.get_full_name(), u.email, u.phone, u.home_city, f"{timezone.localtime(u.date_joined):%Y-%m-%d}"])
                for name, email, phone, city, joined in self.mass_rows:
                    writer.writerow([name, email, phone, city, f"{timezone.localtime(joined):%Y-%m-%d}"])
        block_extra = self.credentials_appendix()
        block = "\n".join([
            start,
            "## Sample users",
            "",
            f"Created by `python manage.py seed_demo_data --wipe --yes` on {timezone.localdate():%d %b %Y}. Re-running it wipes all",
            "visitor activity again and generates new passwords.",
            "",
            "The addresses look real (gmail.com, yahoo.co.in, outlook.com …) and some may belong to real people, so every",
            "sample account is flagged **is_sample** and the site never emails, texts, WhatsApps or pushes to it, even after",
            "real SMTP/SMS providers are configured (see `notifications/mail.py`). Phone numbers, PANs and GSTINs are SAMPLES.",
            "",
            *rows,
            *block_extra,
            end,
        ])
        text = path.read_text(encoding="utf-8") if path.exists() else "# Login details\n"
        if start in text and end in text:
            text = text[: text.index(start)] + block + text[text.index(end) + len(end):]
        else:
            text = text.rstrip() + "\n\n" + block + "\n"
        path.write_text(text, encoding="utf-8")
        self.stdout.write(f"Logins written to {path}")

    def credentials_appendix(self):
        """Codes, cards, receipts and test tips for the login sheet, plus every bulk visitor."""
        from donations.models import Donation
        from memberships.models import Membership
        from promotions.models import GiftVoucher, PromoCode

        fmt = lambda d: f"{d:%d %b %Y}" if d else "-"  # noqa: E731
        lines = ["", "## Codes and cards to test with", "", "### Promo codes", "",
                 "| Code | What it gives | Valid |", "|---|---|---|"]
        for p in PromoCode.objects.order_by("code"):
            valid = f"{fmt(timezone.localtime(p.valid_from)) if p.valid_from else 'now'} to {fmt(timezone.localtime(p.valid_to)) if p.valid_to else 'no end'}"
            lines.append(f"| `{p.code}` | {p.description} | {valid} |")
        lines += ["", "### Gift vouchers (enter in the same box as a promo code)", "",
                  "| Code | Balance | For |", "|---|---|---|"]
        for v in GiftVoucher.objects.order_by("created_at"):
            lines.append(f"| `{v.code}` | ₹{v.balance:,.0f} of ₹{v.initial_value:,.0f} | {v.recipient_name} (valid till {fmt(v.valid_until)}) |")
        lines += ["", "### Heritage Cards", "", "| Card number | Holder | Plan | Valid till |", "|---|---|---|---|"]
        for m in Membership.objects.filter(status="active").select_related("user", "plan").order_by("ends_on"):
            lines.append(f"| `{m.card_number}` | {m.user.get_full_name()} (`{m.user.email}`) | {m.plan.name} | {fmt(m.ends_on)} |")
        lines += ["", "### Donation receipts", "", "| Receipt | Donor | Amount | 80G | Open |", "|---|---|---|---|---|"]
        for d in Donation.objects.filter(status="paid").select_related("user").order_by("paid_at"):
            lines.append(f"| `{d.receipt_number}` | {d.donor_name} | ₹{d.amount:,.0f} | {'Yes' if d.is_80g_eligible else 'No'} | "
                         f"sign in as the donor, then /donations/{d.reference} |")
        lines += [
            "",
            "## Testing without real accounts",
            "",
            "- **Payments:** no Razorpay keys are set, so checkout uses the built-in demo gateway. Pick any method and press Pay;",
            "  nothing is charged. Add real Razorpay keys to `backend/.env` to take live payments.",
            "- **One-time codes (OTP login):** with no SMS/email provider configured, the code is shown on the login screen in",
            "  development. Sample users never receive real email or SMS, by design.",
            "- **Emails:** saved as files in `backend/sent_emails/` (open them in Notepad).",
            "- **Gate check-in:** sign in as staff, open Admin → Gate check-in and scan or type a ticket reference (AA-…) from",
            "  any upcoming booking in Admin → Bookings.",
        ]
        if self.bulk_users:
            lines += [
                "",
                f"## All {len(self.bulk_users)} other sample visitors",
                "",
                f"Every one of them signs in with the password `{self.bulk_password}`. The same list is in",
                "[sample-users.csv](sample-users.csv) for Excel."
                + (f" A further {len(self.mass_rows):,} sample visitors (same password, with their bookings and reviews) are listed"
                   " only in the CSV, as a table that size would not open in an editor." if self.mass_rows else ""),
                "",
                "| # | Name | Email | Password | Phone | City |",
                "|---|---|---|---|---|---|",
            ]
            for i, u in enumerate(self.bulk_users, 1):
                lines.append(f"| {i} | {u.get_full_name()} | `{u.email}` | `{self.bulk_password}` | {u.phone} | {u.home_city} |")
        return lines

    def report(self):
        for key, n in self.counts.items():
            self.stdout.write(f"  {key}: {n}")
        if self.skipped:
            self.stdout.write(f"  skipped {len(self.skipped)} (closed slot/day or rule): " + "; ".join(self.skipped[:6]))
        self.stdout.write(self.style.SUCCESS(f"Sample data ready: {len(self.logins) + len(self.bulk_users) + len(self.mass_rows):,} new users."))
