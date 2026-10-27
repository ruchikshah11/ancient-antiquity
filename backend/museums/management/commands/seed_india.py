"""Seed states/UTs, categories and a starter set of museums across India.

Prices, slots and capacities are SAMPLE values for development - verify with
each museum before going live.

    python manage.py seed_india              # reference data + museums
    python manage.py seed_india --demo-users # also create admin/staff/visitor logins

The 18 museums below carry hand-written detail; the rest of the country comes from
museums/data/india_museums.csv (add rows there, or use `import_museums` for your own file).
"""
import os
import secrets
from datetime import time
from pathlib import Path

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.core.management.base import BaseCommand
from django.db import transaction

from museums.importer import build_slots, import_museums, tickets_for
from museums.models import Category, City, Museum, State, TicketType, TimeSlot

STATES = [
    ("Andhra Pradesh", "AP", False), ("Arunachal Pradesh", "AR", False), ("Assam", "AS", False),
    ("Bihar", "BR", False), ("Chhattisgarh", "CG", False), ("Goa", "GA", False),
    ("Gujarat", "GJ", False), ("Haryana", "HR", False), ("Himachal Pradesh", "HP", False),
    ("Jharkhand", "JH", False), ("Karnataka", "KA", False), ("Kerala", "KL", False),
    ("Madhya Pradesh", "MP", False), ("Maharashtra", "MH", False), ("Manipur", "MN", False),
    ("Meghalaya", "ML", False), ("Mizoram", "MZ", False), ("Nagaland", "NL", False),
    ("Odisha", "OD", False), ("Punjab", "PB", False), ("Rajasthan", "RJ", False),
    ("Sikkim", "SK", False), ("Tamil Nadu", "TN", False), ("Telangana", "TS", False),
    ("Tripura", "TR", False), ("Uttar Pradesh", "UP", False), ("Uttarakhand", "UK", False),
    ("West Bengal", "WB", False),
    ("Andaman and Nicobar Islands", "AN", True), ("Chandigarh", "CH", True),
    ("Dadra and Nagar Haveli and Daman and Diu", "DH", True), ("Delhi", "DL", True),
    ("Jammu and Kashmir", "JK", True), ("Ladakh", "LA", True), ("Lakshadweep", "LD", True),
    ("Puducherry", "PY", True),
]

CATEGORIES = [
    "Archaeology", "Art & Sculpture", "History", "Palace Museum",
    "Science & Technology", "Natural History", "Textiles & Crafts", "Military",
    "Memorial", "Tribal & Folk", "Architecture",
]

DATA_DIR = Path(__file__).resolve().parents[2] / "data"
DATA_FILES = [DATA_DIR / "india_museums.csv", DATA_DIR / "india_heritage_sites.csv"]

MON, TUE, FRI = 0, 1, 4

# name, city, state code, category, tagline, est., managed by, open, close, closed day, featured,
# address, lat, lng, (indian, foreigner, student, child) prices, highlights
MUSEUMS = [
    ("National Museum", "New Delhi", "DL", "Archaeology",
     "Five thousand years of Indian heritage under one roof", 1949, "Ministry of Culture, Govt. of India",
     time(10), time(18), MON, True, "Janpath, Rajpath Area, Central Secretariat, New Delhi 110011",
     28.6118, 77.2196, (20, 650, 0, 0),
     "Harappan gallery with the Dancing Girl\nBuddhist relics from Piprahwa\nMiniature paintings and jewellery"),
    ("Chhatrapati Shivaji Maharaj Vastu Sangrahalaya", "Mumbai", "MH", "History",
     "Indo-Saracenic landmark with art from the Indus to the Mughals", 1922, "CSMVS Trust",
     time(10, 15), time(18), None, True, "159-161 Mahatma Gandhi Road, Fort, Mumbai 400023",
     18.9269, 72.8326, (150, 700, 30, 50),
     "Krishna gallery\nKarl & Meherbai Khandalavala collection\nNatural history section"),
    ("Indian Museum", "Kolkata", "WB", "Archaeology",
     "The oldest and largest museum in India, founded 1814", 1814, "Ministry of Culture, Govt. of India",
     time(10), time(17), MON, True, "27 Jawaharlal Nehru Road, Fitzrovia, Kolkata 700016",
     22.5579, 88.3511, (50, 500, 20, 0),
     "Bharhut stupa railings\nEgyptian mummy\nGandhara sculpture gallery"),
    ("Victoria Memorial Hall", "Kolkata", "WB", "History",
     "Marble memorial with paintings of colonial Calcutta", 1921, "Ministry of Culture, Govt. of India",
     time(10), time(17), MON, False, "1 Queens Way, Maidan, Kolkata 700071",
     22.5448, 88.3426, (50, 500, 20, 0),
     "Calcutta Gallery\nThomas & William Daniell paintings\nRoyal Gallery"),
    ("Salar Jung Museum", "Hyderabad", "TS", "Art & Sculpture",
     "One man's lifelong collection of art from across the world", 1951, "Ministry of Culture, Govt. of India",
     time(10), time(17), FRI, True, "Salar Jung Road, Darushifa, Hyderabad 500002",
     17.3713, 78.4804, (50, 500, 20, 0),
     "Veiled Rebecca marble statue\nMusical clock\nJade and ivory collections"),
    ("Government Museum, Chennai", "Chennai", "TN", "Archaeology",
     "Home to one of the finest Chola bronze collections in the world", 1851, "Department of Museums, Tamil Nadu",
     time(9, 30), time(17), FRI, False, "Pantheon Road, Egmore, Chennai 600008",
     13.0702, 80.2560, (15, 250, 10, 5),
     "Bronze gallery\nAmaravati marbles\nNational Art Gallery building"),
    ("Albert Hall Museum", "Jaipur", "RJ", "Art & Sculpture",
     "Rajasthan's oldest museum in an Indo-Saracenic hall", 1887, "Department of Archaeology & Museums, Rajasthan",
     time(9), time(17), None, True, "Ram Niwas Garden, Kailash Puri, Adarsh Nagar, Jaipur 302004",
     26.9116, 75.8195, (40, 300, 20, 0),
     "Egyptian mummy of Tutu\nPersian golden carpet\nNight viewing of the facade"),
    ("Mehrangarh Fort & Museum", "Jodhpur", "RJ", "Palace Museum",
     "Palanquins, howdahs and armour inside a hilltop fort", 1972, "Mehrangarh Museum Trust",
     time(9), time(17), None, False, "The Fort, Jodhpur 342006",
     26.2978, 73.0185, (200, 600, 100, 100),
     "Phool Mahal\nHowdah gallery\nArms and armour"),
    ("Calico Museum of Textiles", "Ahmedabad", "GJ", "Textiles & Crafts",
     "Four centuries of Indian textiles in a haveli setting", 1949, "Sarabhai Foundation",
     time(10, 30), time(13), TUE, False, "Retreat, Shahibag, Ahmedabad 380004",
     23.0480, 72.5836, (0, 0, 0, 0),
     "Mughal court textiles\nTemple hangings\nGuided tours only"),
    ("Napier Museum", "Thiruvananthapuram", "KL", "Art & Sculpture",
     "Kerala's art museum with bronzes and temple chariots", 1855, "Department of Museums & Zoos, Kerala",
     time(10), time(17), MON, False, "Museum Road, Palayam, Thiruvananthapuram 695033",
     8.5097, 76.9554, (20, 200, 10, 10),
     "Kerala bronzes\nTemple car\nIndo-Saracenic architecture"),
    ("Bihar Museum", "Patna", "BR", "History",
     "A modern museum tracing Bihar from Magadha to the present", 2015, "Government of Bihar",
     time(10), time(17), MON, True, "Bailey Road, Patna 800001",
     25.6102, 85.1215, (100, 500, 50, 50),
     "Didarganj Yakshi\nHistorical galleries\nChildren's gallery"),
    ("Odisha State Museum", "Bhubaneswar", "OD", "Archaeology",
     "Palm-leaf manuscripts and Kalinga sculpture", 1932, "Government of Odisha",
     time(10), time(17), MON, False, "Lewis Road, Bhubaneswar 751014",
     20.2563, 85.8418, (10, 100, 5, 5),
     "Palm-leaf manuscripts\nKalinga sculpture\nTribal heritage gallery"),
    ("Archaeological Museum, Sarnath", "Varanasi", "UP", "Archaeology",
     "Home of the Lion Capital of Ashoka, India's national emblem", 1910, "Archaeological Survey of India",
     time(9), time(17), FRI, True, "Sarnath, Varanasi 221007",
     25.3800, 83.0230, (5, 5, 0, 0),
     "Lion Capital of Ashoka\nPreaching Buddha\nGupta period sculpture"),
    ("Government Museum, Mathura", "Mathura", "UP", "Archaeology",
     "The definitive Kushana and Gupta sculpture collection", 1874, "Department of Culture, Uttar Pradesh",
     time(10, 30), time(16, 30), MON, False, "Dampier Nagar, Mathura 281001",
     27.4924, 77.6737, (5, 25, 0, 0),
     "Headless Kanishka statue\nMathura school Buddhas\nRed sandstone sculpture"),
    ("Visvesvaraya Industrial & Technological Museum", "Bengaluru", "KA", "Science & Technology",
     "Hands-on science named after Sir M. Visvesvaraya", 1962, "National Council of Science Museums",
     time(9, 30), time(18), None, False, "Kasturba Road, Bengaluru 560001",
     12.9752, 77.5963, (85, 85, 60, 60),
     "Engine hall\nWright Flyer replica\nSpace technology gallery"),
    ("Goa State Museum", "Panaji", "GA", "History",
     "Goan heritage from Kadamba sculpture to Christian art", 1977, "Directorate of Archives & Archaeology, Goa",
     time(9, 30), time(17, 30), None, False, "EDC Complex, Patto, Panaji 403001",
     15.4950, 73.8320, (0, 0, 0, 0),
     "Christian art gallery\nNumismatics\nKadamba sculptures"),
    ("Shri Pratap Singh Museum", "Srinagar", "JK", "History",
     "Kashmiri shawls, papier-mache and Gandhara finds", 1898, "Department of Archives, Archaeology & Museums, J&K",
     time(10), time(16), MON, False, "Lal Mandi, Srinagar 190008",
     34.0703, 74.8180, (10, 50, 5, 0),
     "Kashmiri shawls\nHarwan terracotta tiles\nArms gallery"),
    ("National War Memorial & Museum", "New Delhi", "DL", "Military",
     "Honouring India's armed forces since independence", 2019, "Ministry of Defence, Govt. of India",
     time(9), time(19, 30), None, False, "C-Hexagon, India Gate, New Delhi 110001",
     28.6129, 77.2334, (0, 0, 0, 0),
     "Amar Chakra\nParam Yoddha Sthal\nEvening retreat ceremony"),
]

class Command(BaseCommand):
    help = "Seed Indian states, categories and sample museums"

    def add_arguments(self, parser):
        parser.add_argument("--demo-users", action="store_true", help="Create demo admin/staff/visitor accounts")

    @transaction.atomic
    def handle(self, *args, **opts):
        states = {}
        for name, code, ut in STATES:
            states[code], _ = State.objects.update_or_create(
                code=code, defaults={"name": name, "is_union_territory": ut}
            )
        cats = {name: Category.objects.get_or_create(name=name)[0] for name in CATEGORIES}

        created = 0
        for (name, city, st, cat, tagline, est, managed, opening, closing, closed, featured,
             address, lat, lng, prices, highlights) in MUSEUMS:
            city_obj, _ = City.objects.get_or_create(name=city, state=states[st])
            museum, is_new = Museum.objects.get_or_create(
                name=name,
                city=city_obj,
                defaults=dict(
                    category=cats[cat], tagline=tagline, description=f"{name}: {tagline}.",
                    highlights=highlights, address=address, latitude=lat, longitude=lng,
                    established_year=est, managed_by=managed, opening_time=opening,
                    closing_time=closing, closed_weekday=closed, is_featured=featured,
                    place_type="fort" if "Fort" in name else ("palace" if cat == "Palace Museum" else "museum"),
                ),
            )
            if not is_new:
                continue
            created += 1
            for order, ((tname, tdesc), price) in enumerate(zip(tickets_for(museum.managed_by), prices)):
                TicketType.objects.create(museum=museum, name=tname, description=tdesc, price=price, sort_order=order)
            for start, end in build_slots(opening, closing):
                TimeSlot.objects.create(museum=museum, start_time=start, end_time=end, capacity=100)

        result = {"created": 0, "errors": []}
        for path in DATA_FILES:
            with open(path, encoding="utf-8", newline="") as f:
                r = import_museums(f)
            result["created"] += r["created"]
            result["errors"] += [{**e, "row": f"{path.name}:{e['row']}"} for e in r["errors"]]
        call_command("enrich_museums", stdout=self.stdout)  # photos + descriptions from the cached Wikipedia data
        for err in result["errors"]:
            self.stderr.write(f"  row {err['row']}: {err['error']}")

        self.stdout.write(self.style.SUCCESS(
            f"{len(states)} states/UTs, {len(cats)} categories, "
            f"{created + result['created']} new museums ({Museum.objects.count()} total)"
        ))

        if opts["demo_users"]:
            User = get_user_model()
            # Passwords come from .env (DEMO_*_PASSWORD); a random one is generated when unset.
            def demo_password(role):
                return os.getenv(f"DEMO_{role}_PASSWORD") or f"Demo-{secrets.token_urlsafe(9)}!"

            demo = [
                ("admin@ancientantiquity.in", demo_password("ADMIN"), User.Role.ADMIN, True),
                ("staff@ancientantiquity.in", demo_password("STAFF"), User.Role.STAFF, False),
                ("visitor@ancientantiquity.in", demo_password("VISITOR"), User.Role.VISITOR, False),
            ]
            for email, pwd, role, superuser in demo:
                if User.objects.filter(email=email).exists():
                    continue
                if superuser:
                    User.objects.create_superuser(email=email, password=pwd, first_name="Site", last_name="Admin")
                else:
                    User.objects.create_user(email=email, password=pwd, role=role, first_name=role.label.split()[0])
                self.stdout.write(f"  created {email} / {pwd}")
