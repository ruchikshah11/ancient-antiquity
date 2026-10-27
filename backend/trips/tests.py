import datetime
from decimal import Decimal

from bookings.tests.factories import APITestCase, client_for, make_city, make_museum, make_visitor
from museums.models import Museum

from .geo import haversine_km
from .models import Favourite, Trip, TripStop


class GeoTests(APITestCase):
    def setUp(self):
        super().setUp()
        self.jaipur = make_city(name="Jaipur")
        self.agra = make_city(name="Agra")
        self.amber = make_museum(
            "Amber Fort", city=self.jaipur, place_type=Museum.PlaceType.FORT,
            latitude=Decimal("26.985500"), longitude=Decimal("75.851300"),
            image_url="https://upload.wikimedia.org/x/1280px-Amber.jpg",
        )
        self.hawa = make_museum("Hawa Mahal", city=self.jaipur, place_type=Museum.PlaceType.PALACE)  # no pin
        self.taj = make_museum(
            "Taj Museum", city=self.agra, latitude=Decimal("27.175100"), longitude=Decimal("78.042100"),
        )
        self.nowhere = make_museum("Unknown Museum")  # no pin, no located neighbour
        self.hidden = make_museum("Hidden", city=self.agra, latitude=Decimal("27.1"), longitude=Decimal("78.0"), is_active=False)

    def test_haversine(self):
        self.assertAlmostEqual(haversine_km(26.9855, 75.8513, 27.1751, 78.0421), 218, delta=5)
        self.assertEqual(haversine_km(10, 10, 10, 10), 0)

    def test_geo_lists_located_active_places_with_city_fallback(self):
        r = client_for().get("/api/places/geo/")
        self.assertEqual(r.status_code, 200)
        rows = {p["slug"]: p for p in r.data}
        self.assertEqual(set(rows), {self.amber.slug, self.hawa.slug, self.taj.slug})
        self.assertFalse(rows[self.amber.slug]["approximate"])
        self.assertTrue(rows[self.hawa.slug]["approximate"])
        self.assertEqual(rows[self.hawa.slug]["lat"], rows[self.amber.slug]["lat"])
        self.assertIn("/330px-", rows[self.amber.slug]["image_url"])
        self.assertEqual(rows[self.amber.slug]["starting_price"], "50.00")
        self.assertEqual(rows[self.amber.slug]["city"], "Jaipur")

    def test_geo_type_filter(self):
        r = client_for().get("/api/places/geo/", {"type": "fort,palace"})
        self.assertEqual({p["slug"] for p in r.data}, {self.amber.slug, self.hawa.slug})

    def test_nearby_sorted_by_distance_within_radius(self):
        r = client_for().get("/api/places/nearby/", {"lat": "26.92", "lng": "75.82", "radius_km": 500})
        self.assertEqual(r.status_code, 200)
        slugs = [p["slug"] for p in r.data["results"]]
        self.assertEqual(slugs[-1], self.taj.slug)
        self.assertLess(r.data["results"][0]["distance_km"], 10)
        small = client_for().get("/api/places/nearby/", {"lat": "26.92", "lng": "75.82", "radius_km": 50})
        self.assertNotIn(self.taj.slug, [p["slug"] for p in small.data["results"]])
        self.assertEqual(small.data["count"], 2)

    def test_nearby_validates_params(self):
        self.assertEqual(client_for().get("/api/places/nearby/").status_code, 400)
        self.assertEqual(client_for().get("/api/places/nearby/", {"lat": "x", "lng": "1"}).status_code, 400)
        self.assertEqual(client_for().get("/api/places/nearby/", {"lat": "91", "lng": "1"}).status_code, 400)
        self.assertEqual(client_for().get("/api/places/nearby/", {"lat": "nan", "lng": "1"}).status_code, 400)


class FavouriteTests(APITestCase):
    def setUp(self):
        super().setUp()
        self.user = make_visitor()
        self.place = make_museum("Red Fort")
        self.other = make_museum("City Palace")

    def test_requires_login(self):
        self.assertEqual(client_for().get("/api/favourites/").status_code, 401)
        self.assertEqual(client_for().post("/api/favourites/", {"museum": self.place.slug}).status_code, 401)

    def test_add_list_ids_remove(self):
        c = client_for(self.user)
        self.assertEqual(c.post("/api/favourites/", {"museum": self.place.slug}).status_code, 201)
        self.assertEqual(c.post("/api/favourites/", {"museum": self.place.slug}).status_code, 200)  # idempotent
        self.assertEqual(Favourite.objects.filter(user=self.user).count(), 1)
        self.assertEqual(c.get("/api/favourites/ids/").data, [self.place.slug])
        listing = c.get("/api/favourites/").data
        self.assertEqual(listing[0]["museum"]["slug"], self.place.slug)
        self.assertIn("starting_price", listing[0]["museum"])
        self.assertEqual(c.delete(f"/api/favourites/{self.place.slug}/").status_code, 204)
        self.assertEqual(c.get("/api/favourites/ids/").data, [])

    def test_unknown_or_inactive_place(self):
        c = client_for(self.user)
        self.assertEqual(c.post("/api/favourites/", {"museum": "nope"}).status_code, 404)
        self.assertEqual(c.post("/api/favourites/", {}).status_code, 400)
        hidden = make_museum("Hidden", is_active=False)
        self.assertEqual(c.post("/api/favourites/", {"museum": hidden.slug}).status_code, 404)

    def test_users_see_only_their_own(self):
        Favourite.objects.create(user=make_visitor(), museum=self.other)
        self.assertEqual(client_for(self.user).get("/api/favourites/ids/").data, [])


class TripTests(APITestCase):
    def setUp(self):
        super().setUp()
        self.user = make_visitor()
        self.c = client_for(self.user)
        self.a = make_museum("Place A", latitude=Decimal("28.6"), longitude=Decimal("77.2"), closed_weekday=0)
        self.b = make_museum("Place B")
        self.c3 = make_museum("Place C")
        start = datetime.date(2030, 1, 7)
        self.trip = self.c.post(
            "/api/trips/", {"title": " Delhi weekend ", "start_date": start, "end_date": start + datetime.timedelta(days=2)}
        ).data

    def url(self, suffix=""):
        return f"/api/trips/{self.trip['id']}/{suffix}"

    def add(self, museum, day=1, **extra):
        return self.c.post(self.url("stops/"), {"museum": museum.slug, "day": day, **extra}, format="json")

    def test_create_and_list(self):
        self.assertEqual(self.trip["title"], "Delhi weekend")
        self.assertEqual(self.trip["day_count"], 3)
        listing = self.c.get("/api/trips/").data
        self.assertEqual(len(listing), 1)
        self.assertEqual(listing[0]["stop_count"], 0)

    def test_validation(self):
        r = self.c.post("/api/trips/", {"title": "x", "start_date": "2030-01-05", "end_date": "2030-01-01"})
        self.assertEqual(r.status_code, 400)
        self.assertEqual(self.c.post("/api/trips/", {"title": "  "}).status_code, 400)
        self.assertEqual(self.add(self.a, day=4).status_code, 400)  # trip has 3 days
        self.assertEqual(self.c.post(self.url("stops/"), {"museum": "nope"}).status_code, 400)

    def test_owner_only(self):
        other = client_for(make_visitor())
        self.assertEqual(other.get(self.url()).status_code, 404)
        self.assertEqual(other.post(self.url("stops/"), {"museum": self.a.slug}).status_code, 404)
        self.assertEqual(other.delete(self.url()).status_code, 404)
        self.assertEqual(client_for().get("/api/trips/").status_code, 401)

    def test_stops_add_update_delete(self):
        r = self.add(self.a, planned_time="10:00")
        self.assertEqual(r.status_code, 201)
        self.assertEqual(r.data["place"]["slug"], self.a.slug)
        self.assertEqual(r.data["place"]["closed_weekday"], 0)
        self.assertEqual(r.data["place"]["lat"], 28.6)
        second = self.add(self.b).data
        self.assertEqual(second["order"], 1)
        r = self.c.patch(self.url(f"stops/{second['id']}/"), {"day": 2, "notes": "Lunch nearby"}, format="json")
        self.assertEqual(r.status_code, 200)
        self.assertEqual((r.data["day"], r.data["order"], r.data["notes"]), (2, 0, "Lunch nearby"))
        self.assertEqual(self.c.delete(self.url(f"stops/{second['id']}/")).status_code, 204)
        detail = self.c.get(self.url()).data
        self.assertEqual([s["place"]["slug"] for s in detail["stops"]], [self.a.slug])
        self.assertEqual(detail["stop_count"], 1)

    def test_reorder(self):
        ids = [self.add(m).data["id"] for m in (self.a, self.b, self.c3)]
        r = self.c.post(self.url("reorder/"), {"day": 1, "stop_ids": [ids[2], ids[0], ids[1]]}, format="json")
        self.assertEqual(r.status_code, 200)
        self.assertEqual([s["id"] for s in r.data["stops"]], [ids[2], ids[0], ids[1]])
        # move one stop to day 2 via reorder
        r = self.c.post(self.url("reorder/"), {"day": 2, "stop_ids": [ids[0]]}, format="json")
        self.assertEqual(TripStop.objects.get(pk=ids[0]).day, 2)
        bad = self.c.post(self.url("reorder/"), {"day": 1, "stop_ids": [ids[0], 99999]}, format="json")
        self.assertEqual(bad.status_code, 400)
        self.assertEqual(self.c.post(self.url("reorder/"), {"day": 9, "stop_ids": []}, format="json").status_code, 400)

    def test_shortening_trip_keeps_stops(self):
        self.add(self.a, day=1)
        self.add(self.b, day=3)
        r = self.c.patch(self.url(), {"end_date": "2030-01-08"}, format="json")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(sorted(TripStop.objects.values_list("day", flat=True)), [1, 2])

    def test_delete_trip_removes_stops(self):
        self.add(self.a)
        self.assertEqual(self.c.delete(self.url()).status_code, 204)
        self.assertFalse(Trip.objects.exists())
        self.assertFalse(TripStop.objects.exists())

    def test_stops_carry_planned_date_nearest_slot_and_date_price(self):
        from museums.models import PriceRule

        # make_museum slots: 10:00-11:00 and 14:00-15:00; Indian adult 50
        slots = list(self.b.slots.order_by("start_time"))
        PriceRule.objects.create(museum=self.b, name="Weekend", weekdays="5,6", value=20)
        self.add(self.b, day=1, planned_time="10:30")   # 2030-01-07 Monday, inside the 10:00 slot
        self.add(self.b, day=2, planned_time="13:00")   # nearest start: 14:00
        self.add(self.c3, day=3)                        # no planned time
        stops = self.c.get(self.url()).data["stops"]
        self.assertEqual([s["visit_date"] for s in stops], [datetime.date(2030, 1, 7), datetime.date(2030, 1, 8),
                                                            datetime.date(2030, 1, 9)])
        self.assertEqual([s["slot_id"] for s in stops], [slots[0].id, slots[1].id, None])
        self.assertEqual(stops[0]["price_on_date"], "50.00")
        # a Saturday trip picks up the weekend price
        self.c.patch(self.url(), {"start_date": "2030-01-05", "end_date": "2030-01-07"}, format="json")
        stops = self.c.get(self.url()).data["stops"]
        self.assertEqual(stops[0]["price_on_date"], "60.00")

    def test_undated_trip_has_no_visit_dates(self):
        trip = self.c.post("/api/trips/", {"title": "Someday"}).data
        r = self.c.post(f"/api/trips/{trip['id']}/stops/", {"museum": self.b.slug, "planned_time": "10:00"}, format="json")
        self.assertEqual((r.data["visit_date"], r.data["slot_id"], r.data["price_on_date"]), (None, None, None))
