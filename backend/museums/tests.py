import datetime
import io
import shutil
import tempfile
import unittest
from pathlib import Path

from django.conf import settings
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import override_settings
from django.utils import timezone
from PIL import Image

from bookings import services
from bookings.models import Booking
from bookings.tests.factories import (
    APITestCase, at, book, client_for, first_slot, frozen_now, future_open_date, make_admin, make_category,
    make_city, make_museum, make_staff, make_state, make_visitor,
)
from museums.models import Museum, MuseumImage, Review


def results(response):
    return response.data["results"] if isinstance(response.data, dict) and "results" in response.data else response.data


def slugs(response):
    return {m["slug"] for m in results(response)}


class MuseumListAndFacetTests(APITestCase):
    def setUp(self):
        super().setUp()
        self.s1, self.s2 = make_state("Rajasthan", "RJ"), make_state("Delhi", "DL")
        c1, c2 = make_city(self.s1, "Jaipur"), make_city(self.s2, "New Delhi")
        self.cat = make_category("Archaeology")
        self.museum = make_museum("City Museum", city=c1, category=self.cat, is_featured=True)
        self.fort1 = make_museum("Amber Fort", city=c1, place_type=Museum.PlaceType.FORT)
        self.fort2 = make_museum("Red Fort", city=c2, place_type=Museum.PlaceType.FORT, category=self.cat)
        self.hidden = make_museum("Closed Palace", city=c2, place_type=Museum.PlaceType.PALACE, is_active=False)

    def test_filter_by_type(self):
        r = client_for().get("/api/museums/", {"type": "fort"})
        self.assertEqual(slugs(r), {self.fort1.slug, self.fort2.slug})

    def test_filter_by_state_and_featured(self):
        self.assertEqual(slugs(client_for().get("/api/museums/", {"state": self.s1.id})), {self.museum.slug, self.fort1.slug})
        self.assertEqual(slugs(client_for().get("/api/museums/", {"featured": "true"})), {self.museum.slug})

    def test_inactive_places_hidden_from_public_but_shown_to_panel(self):
        self.assertNotIn(self.hidden.slug, slugs(client_for().get("/api/museums/")))
        self.assertEqual(client_for().get(f"/api/museums/{self.hidden.slug}/").status_code, 404)
        self.assertIn(self.hidden.slug, slugs(client_for(make_admin()).get("/api/museums/")))

    def test_facets_exclude_their_own_filter(self):
        r = client_for().get("/api/museums/facets/", {"type": "fort"})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.data["total"], 2)
        # type counts ignore ?type, so the other types are still offered (inactive palace excluded)
        self.assertEqual(r.data["type"], {"museum": 1, "fort": 2})
        # state counts respect ?type
        self.assertEqual(r.data["state"], {str(self.s1.id): 1, str(self.s2.id): 1})
        self.assertEqual(r.data["category"], {str(self.cat.id): 1})

        r = client_for().get("/api/museums/facets/", {"type": "fort", "state": self.s1.id})
        self.assertEqual(r.data["total"], 1)
        self.assertEqual(r.data["state"], {str(self.s1.id): 1, str(self.s2.id): 1})
        self.assertEqual(r.data["type"], {"museum": 1, "fort": 1})

    # BUG: MuseumViewSet.get_queryset() annotates Avg/Count (a GROUP BY query), and Django ignores
    # Meta.ordering for GROUP BY queries, so the list SQL has no ORDER BY at all (DRF also warns
    # "UnorderedObjectListWarning"). The default A-Z order is lost and, on Postgres, paginated pages can
    # repeat or skip places. Fix idea: add .order_by("name", "id") to the queryset.
    def test_default_list_order_is_alphabetical(self):
        make_museum("Zoological Museum")  # created last, sorts last
        make_museum("Aaa Archive")        # created last, sorts first
        names = [m["name"] for m in results(client_for().get("/api/museums/"))]
        self.assertEqual(names, sorted(names))

    def test_staff_assigned_filter_only_shows_their_places(self):
        staff = make_staff(self.fort1)
        self.assertEqual(slugs(client_for(staff).get("/api/museums/", {"assigned": 1})), {self.fort1.slug})
        self.assertEqual(len(slugs(client_for(staff).get("/api/museums/"))), 4)  # browsing still shows all
        # admins are never narrowed down
        self.assertEqual(len(slugs(client_for(make_admin()).get("/api/museums/", {"assigned": 1}))), 4)


class MuseumAdminEditTests(APITestCase):
    def setUp(self):
        super().setUp()
        self.museum = make_museum("Edit Me")
        self.url = f"/api/museums/{self.museum.slug}/"

    def test_only_admins_can_edit(self):
        payload = {"tagline": "New tagline"}
        self.assertEqual(client_for().patch(self.url, payload, format="json").status_code, 401)
        self.assertEqual(client_for(make_visitor()).patch(self.url, payload, format="json").status_code, 403)
        self.assertEqual(client_for(make_staff(self.museum)).patch(self.url, payload, format="json").status_code, 403)
        r = client_for(make_admin()).patch(self.url, payload, format="json")
        self.assertEqual(r.status_code, 200, r.data)
        self.museum.refresh_from_db()
        self.assertEqual(self.museum.tagline, "New tagline")

    def test_info_verified_records_who_and_when(self):
        admin = make_admin(first_name="Nita", last_name="Shah")
        r = client_for(admin).patch(self.url, {"info_verified": True}, format="json")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.data["info_verified_by_name"], "Nita Shah")
        self.assertIsNotNone(r.data["info_verified_at"])
        r = client_for(admin).patch(self.url, {"info_verified": False}, format="json")
        self.assertIsNone(r.data["info_verified_by_name"])

    def test_closing_time_must_follow_opening(self):
        r = client_for(make_admin()).patch(self.url, {"opening_time": "18:00", "closing_time": "09:00"}, format="json")
        self.assertEqual(r.status_code, 400)
        self.assertIn("closing_time", r.data)

    def test_admin_assigns_staff_to_places(self):
        staff = make_staff()
        r = client_for(make_admin()).put(f"/api/admin/staff/{staff.id}/museums/", {"museums": [self.museum.slug]}, format="json")
        self.assertEqual(r.status_code, 200, r.data)
        self.assertEqual(list(staff.assigned_museums.all()), [self.museum])
        r = client_for(make_admin()).put(f"/api/admin/staff/{staff.id}/museums/", {"museums": ["no-such-place"]}, format="json")
        self.assertEqual(r.status_code, 400)


class AvailabilityTests(APITestCase):
    def setUp(self):
        super().setUp()
        self.museum = make_museum(closed_weekday=0)  # closed on Mondays
        self.slot10, self.slot14 = self.museum.slots.order_by("start_time")
        self.url = f"/api/museums/{self.museum.slug}/availability/"
        self.day = future_open_date(self.museum)

    def get(self, day, user=None, **params):
        return client_for(user).get(self.url, {"date": str(day), **params})

    def test_date_is_required(self):
        self.assertEqual(client_for().get(self.url).status_code, 400)

    def test_open_day_reports_remaining_seats(self):
        book(make_visitor(), self.museum, self.slot10, self.day, qty=3, confirm=True)
        r = self.get(self.day)
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.data["bookable"])
        first = r.data["slots"][0]
        self.assertEqual((first["booked"], first["available"]), (3, 97))
        self.assertTrue(first["bookable"])

    def test_closed_weekday(self):
        monday = self.day + datetime.timedelta(days=(0 - self.day.weekday()) % 7)
        r = self.get(monday)
        self.assertTrue(r.data["closed"])
        self.assertFalse(r.data["bookable"])
        self.assertFalse(any(s["bookable"] for s in r.data["slots"]))

    def test_outside_booking_window(self):
        today = timezone.localdate()
        for day in (today - datetime.timedelta(days=1), today + datetime.timedelta(days=settings.BOOKING_WINDOW_DAYS + 1)):
            r = self.get(day)
            self.assertFalse(r.data["bookable"], day)

    def test_full_slot_not_bookable(self):
        small = make_museum(slots=[(datetime.time(10), datetime.time(11), 2)])
        book(make_visitor(), small, first_slot(small), self.day, qty=2)  # pending holds count too
        r = client_for().get(f"/api/museums/{small.slug}/availability/", {"date": str(self.day)})
        self.assertEqual(r.data["slots"][0]["available"], 0)
        self.assertFalse(r.data["slots"][0]["bookable"])

    def test_slot_that_started_today_is_not_bookable_online_but_is_at_the_counter(self):
        day = future_open_date(self.museum, 2)
        with frozen_now(at(day, 10, 30)):
            r = self.get(day)
            started, later = r.data["slots"]
            self.assertFalse(started["bookable"])
            self.assertTrue(later["bookable"])
            # Counter staff may still sell into the running 10:00-11:00 slot
            r = self.get(day, user=make_staff(self.museum), counter=1)
            self.assertTrue(r.data["slots"][0]["bookable"])

    def test_group_available_respects_slot_share(self):
        # capacity 100 -> groups may take 30; a 25-person group leaves 5
        services.create_booking(
            user=make_visitor(), museum=self.museum, slot=self.slot10, visit_date=self.day,
            items=[{"ticket_type": self.museum.ticket_types.first(), "quantity": 25}],
            visitor_name="School", group_type=Booking.GroupType.TOUR, organisation_name="Tours Ltd",
        )
        r = self.get(self.day)
        self.assertEqual(r.data["slots"][0]["group_available"], 5)
        self.assertEqual(r.data["slots"][1]["group_available"], 30)

        Museum.objects.filter(pk=self.museum.pk).update(allow_groups=False)
        r = self.get(self.day)
        self.assertEqual(r.data["slots"][1]["group_available"], 0)


class ReviewTests(APITestCase):
    def setUp(self):
        super().setUp()
        self.museum = make_museum()
        self.url = f"/api/museums/{self.museum.slug}/reviews/"
        self.visitor = make_visitor(first_name="Kiran", last_name="Patel")
        self.payload = {"rating": 5, "title": "Wonderful", "comment": "Loved the sculptures."}

    def post(self, user=None):
        return client_for(user or self.visitor).post(self.url, self.payload, format="json")

    def test_anonymous_can_read_but_not_write(self):
        r = client_for().get(self.url)
        self.assertEqual(r.status_code, 200)
        self.assertFalse(r.data["can_review"])
        self.assertEqual(client_for().post(self.url, self.payload, format="json").status_code, 401)

    def test_visitor_without_visit_cannot_review(self):
        self.assertEqual(self.post().status_code, 400)
        # a future paid ticket is not a visit yet
        book(self.visitor, self.museum, confirm=True)
        self.assertEqual(self.post().status_code, 400)

    def test_past_confirmed_visit_can_review(self):
        book(self.visitor, self.museum, visit_date=timezone.localdate() - datetime.timedelta(days=3), confirm=True)
        r = self.post()
        self.assertEqual(r.status_code, 201, r.data)
        self.assertEqual(r.data["user_name"], "Kiran P.")
        # posting again updates the same review
        self.payload["rating"] = 4
        self.post()
        self.assertEqual(Review.objects.get(user=self.visitor).rating, 4)
        summary = client_for().get(self.url).data
        self.assertEqual((summary["count"], summary["average"]), (1, 4.0))

    def test_half_star_ratings(self):
        book(self.visitor, self.museum, visit_date=timezone.localdate() - datetime.timedelta(days=3), confirm=True)
        for bad in (1.8, 0, 5.5, 4.25):
            self.payload["rating"] = bad
            self.assertEqual(self.post().status_code, 400, bad)
        for good in (0.5, 4.5):
            self.payload["rating"] = good
            r = self.post()
            self.assertIn(r.status_code, (200, 201), r.data)
            self.assertEqual(r.data["rating"], good)  # a JSON number, not "4.5"
        summary = client_for().get(self.url).data
        self.assertEqual(summary["average"], 4.5)
        self.assertEqual((summary["breakdown"]["4"], summary["breakdown"]["5"]), (1, 0))  # 4.5 is in the 4-star bar

    def test_admin_filter_buckets_half_stars_and_cannot_change_rating(self):
        book(self.visitor, self.museum, visit_date=timezone.localdate() - datetime.timedelta(days=3), confirm=True)
        self.payload["rating"] = 4.5
        self.post()
        review = Review.objects.get(user=self.visitor)
        admin = client_for(make_admin())
        found = lambda n: [r["id"] for r in results(admin.get("/api/admin/reviews/", {"rating": n}))]  # noqa: E731
        self.assertEqual((found(4), found(5)), ([review.id], []))
        admin.patch(f"/api/admin/reviews/{review.id}/", {"rating": 1, "is_published": False}, format="json")
        review.refresh_from_db()
        self.assertEqual((float(review.rating), review.is_published), (4.5, False))

    def test_reviews_page_sort_and_star_filter(self):
        ratings = ["5", "4.5", "4", "3", "2", "5", "4"]
        made = []
        for i, rating in enumerate(ratings):
            user = make_visitor()
            with frozen_now(at(timezone.localdate() - datetime.timedelta(days=10 - i), 12)):
                made.append(Review.objects.create(museum=self.museum, user=user, rating=Decimal(rating), comment=f"r{i}"))
        first = client_for().get(self.url).data  # newest first, 5 per page
        self.assertEqual([r["comment"] for r in first["results"]], ["r6", "r5", "r4", "r3", "r2"])
        self.assertEqual((first["results_total"], first["next_offset"]), (7, 5))
        more = client_for().get(self.url, {"offset": 5, "limit": 10}).data
        self.assertEqual(([r["comment"] for r in more["results"]], more["next_offset"]), (["r1", "r0"], None))
        oldest = client_for().get(self.url, {"sort": "oldest"}).data
        self.assertEqual(oldest["results"][0]["comment"], "r0")
        four = client_for().get(self.url, {"stars": 4}).data  # the 4-star bar: 4 and 4.5
        self.assertEqual(sorted(r["comment"] for r in four["results"]), ["r1", "r2", "r6"])
        self.assertEqual(four["count"], 7)  # the summary still covers every review
        mine = client_for(made[0].user).get(self.url).data
        self.assertNotIn("r0", [r["comment"] for r in mine["results"]])  # your own review is shown separately
        self.assertEqual(mine["my_review"]["comment"], "r0")

    def test_checked_in_visit_can_review(self):
        booking = book(self.visitor, self.museum, visit_date=timezone.localdate(), confirm=True)
        services.mark_checked_in(booking, make_staff(self.museum))
        self.assertEqual(self.post().status_code, 201)

    def test_cancelled_past_booking_cannot_review(self):
        booking = book(self.visitor, self.museum, visit_date=timezone.localdate() - datetime.timedelta(days=3), confirm=True)
        Booking.objects.filter(pk=booking.pk).update(status=Booking.Status.CANCELLED)
        self.assertEqual(self.post().status_code, 400)


class PhotoUploadTests(APITestCase):
    def setUp(self):
        super().setUp()
        self.media = tempfile.mkdtemp(prefix="aa-test-media-")
        self.addCleanup(shutil.rmtree, self.media, ignore_errors=True)
        override = override_settings(MEDIA_ROOT=self.media)
        override.enable()
        self.addCleanup(override.disable)
        self.museum = make_museum()
        self.url = f"/api/museums/{self.museum.slug}/photos/"
        self.admin = make_admin()

    @staticmethod
    def image(fmt="PNG", name="photo.png"):
        buf = io.BytesIO()
        Image.new("RGB", (8, 8), "orange").save(buf, format=fmt)
        return SimpleUploadedFile(name, buf.getvalue(), content_type=f"image/{fmt.lower()}")

    def test_admin_uploads_gallery_photo(self):
        r = client_for(self.admin).post(self.url, {"file": self.image(), "caption": "Gate"}, format="multipart")
        self.assertEqual(r.status_code, 201, r.data)
        image = MuseumImage.objects.get(museum=self.museum)
        self.assertEqual(image.caption, "Gate")
        files = list(Path(self.media, "places", self.museum.slug).iterdir())
        self.assertEqual(len(files), 1)
        self.assertEqual(files[0].suffix, ".png")

    def test_make_main_sets_main_image(self):
        r = client_for(self.admin).post(self.url, {"file": self.image("JPEG", "a.jpg"), "make_main": "1"}, format="multipart")
        self.assertEqual(r.status_code, 201, r.data)
        self.museum.refresh_from_db()
        self.assertTrue(self.museum.image_url.endswith(".jpg"))
        self.assertFalse(MuseumImage.objects.exists())

    def test_non_image_rejected(self):
        fake = SimpleUploadedFile("evil.jpg", b"<?php echo 'hi'; ?>", content_type="image/jpeg")
        r = client_for(self.admin).post(self.url, {"file": fake}, format="multipart")
        self.assertEqual(r.status_code, 400)
        self.assertIn("not a readable image", str(r.data["file"]))
        self.assertFalse(MuseumImage.objects.exists())

    def test_unsupported_format_rejected(self):
        r = client_for(self.admin).post(self.url, {"file": self.image("GIF", "a.gif")}, format="multipart")
        self.assertEqual(r.status_code, 400)
        self.assertIn("Only JPG", str(r.data["file"]))

    def test_oversize_rejected(self):
        with override_settings(MAX_UPLOAD_MB=0):
            r = client_for(self.admin).post(self.url, {"file": self.image()}, format="multipart")
        self.assertEqual(r.status_code, 400)

    def test_non_admin_cannot_upload(self):
        r = client_for(make_staff(self.museum)).post(self.url, {"file": self.image()}, format="multipart")
        self.assertEqual(r.status_code, 403)


# ------------------------------------------------------------------ closures, pricing, facilities, crowd

from decimal import Decimal  # noqa: E402

from django.core.management import call_command  # noqa: E402

from bookings.tests.factories import add_slot, booking_payload, ticket  # noqa: E402
from museums.models import PlaceClosure, PriceRule  # noqa: E402


class ClosureTests(APITestCase):
    def setUp(self):
        super().setUp()
        self.museum = make_museum()
        self.slot10, self.slot14 = self.museum.slots.order_by("start_time")
        self.day = future_open_date(self.museum)
        self.url = f"/api/museums/{self.museum.slug}/availability/"

    def test_whole_day_closure_closes_availability_and_booking(self):
        PlaceClosure.objects.create(museum=self.museum, start_date=self.day, end_date=self.day, reason="Floor repairs")
        r = client_for().get(self.url, {"date": str(self.day)})
        self.assertTrue(r.data["closed"])
        self.assertEqual(r.data["closure_reason"], "Floor repairs")
        self.assertFalse(any(s["bookable"] for s in r.data["slots"]))
        r = client_for(make_visitor()).post("/api/bookings/", booking_payload(self.museum, self.slot10, self.day), format="json")
        self.assertEqual(r.status_code, 400)
        self.assertIn("Floor repairs", str(r.data["visit_date"]))

    def test_all_place_closure_applies_everywhere(self):
        PlaceClosure.objects.create(museum=None, start_date=self.day - datetime.timedelta(days=1),
                                    end_date=self.day, reason="National holiday")
        r = client_for().get(self.url, {"date": str(self.day)})
        self.assertTrue(r.data["closed"])
        with self.assertRaises(Exception):
            book(make_visitor(), self.museum, self.slot10, self.day)  # the service layer refuses too

    def test_partial_closure_disables_listed_slots_only(self):
        c = PlaceClosure.objects.create(museum=self.museum, start_date=self.day, end_date=self.day,
                                        reason="VIP visit", all_day=False)
        c.slots.add(self.slot10)
        r = client_for().get(self.url, {"date": str(self.day)})
        self.assertFalse(r.data["closed"])
        first, second = r.data["slots"]
        self.assertEqual((first["bookable"], first["closed_reason"]), (False, "VIP visit"))
        self.assertTrue(second["bookable"])
        r = client_for(make_visitor()).post("/api/bookings/", booking_payload(self.museum, self.slot10, self.day), format="json")
        self.assertEqual(r.status_code, 400)
        self.assertIn("slot", r.data)
        r = client_for(make_visitor()).post("/api/bookings/", booking_payload(self.museum, self.slot14, self.day), format="json")
        self.assertEqual(r.status_code, 201, r.data)

    def test_counter_sale_refused_on_closed_day(self):
        slot = add_slot(self.museum)
        today = timezone.localdate()
        PlaceClosure.objects.create(museum=self.museum, start_date=today, end_date=today, reason="Strike")
        payload = booking_payload(self.museum, slot, today, payment_method="cash")
        payload.pop("visit_date")
        r = client_for(make_staff(self.museum)).post("/api/bookings/counter/", payload, format="json")
        self.assertEqual(r.status_code, 400)
        self.assertIn("Strike", str(r.data))

    def test_public_closures_list(self):
        PlaceClosure.objects.create(museum=self.museum, start_date=self.day, end_date=self.day, reason="Repairs")
        PlaceClosure.objects.create(museum=None, start_date=self.day, end_date=self.day, reason="Holiday")
        PlaceClosure.objects.create(museum=make_museum(), start_date=self.day, end_date=self.day, reason="Elsewhere")
        PlaceClosure.objects.create(museum=self.museum, start_date=self.day - datetime.timedelta(days=400),
                                    end_date=self.day - datetime.timedelta(days=399), reason="Long ago")
        r = client_for().get(f"/api/museums/{self.museum.slug}/closures/")
        self.assertEqual({c["reason"] for c in r.data}, {"Repairs", "Holiday"})
        self.assertEqual([c["all_places"] for c in r.data if c["reason"] == "Holiday"], [True])

    def test_admin_crud_and_staff_read_only(self):
        admin, staff = make_admin(), make_staff(self.museum)
        body = {"museum": self.museum.slug, "start_date": str(self.day), "end_date": str(self.day),
                "reason": "Maintenance", "all_day": False, "slot_ids": [self.slot14.id]}
        self.assertEqual(client_for(staff).post("/api/admin/closures/", body, format="json").status_code, 403)
        r = client_for(admin).post("/api/admin/closures/", body, format="json")
        self.assertEqual(r.status_code, 201, r.data)
        closure = PlaceClosure.objects.get(pk=r.data["id"])
        self.assertEqual((closure.created_by, list(closure.slots.all())), (admin, [self.slot14]))
        # staff see the closures of their own places (and all-place ones), not other places
        PlaceClosure.objects.create(museum=make_museum(), start_date=self.day, end_date=self.day, reason="Other")
        r = client_for(staff).get("/api/admin/closures/")
        self.assertEqual([c["reason"] for c in r.data], ["Maintenance"])
        r = client_for(admin).patch(f"/api/admin/closures/{closure.id}/", {"all_day": True}, format="json")
        self.assertEqual(r.status_code, 200, r.data)
        self.assertEqual(closure.slots.count(), 0)
        self.assertEqual(client_for(admin).delete(f"/api/admin/closures/{closure.id}/").status_code, 204)

    def test_closure_validation(self):
        admin = make_admin()
        other_slot = first_slot(make_museum())
        base = {"museum": self.museum.slug, "start_date": str(self.day), "end_date": str(self.day), "reason": "X"}
        bad = [
            {**base, "end_date": str(self.day - datetime.timedelta(days=1))},
            {**base, "all_day": False},
            {**base, "all_day": False, "slot_ids": [other_slot.id]},
            {**base, "museum": None, "all_day": False, "slot_ids": [self.slot10.id]},
        ]
        for body in bad:
            self.assertEqual(client_for(admin).post("/api/admin/closures/", body, format="json").status_code, 400, body)

    def test_seed_holidays_is_idempotent(self):
        call_command("seed_holidays", stdout=io.StringIO())
        call_command("seed_holidays", stdout=io.StringIO())
        rows = PlaceClosure.objects.filter(museum=None)
        self.assertEqual(rows.count(), 3)
        self.assertEqual({r.start_date for r in rows},
                         {datetime.date(2026, 1, 26), datetime.date(2026, 8, 15), datetime.date(2026, 10, 2)})
        self.assertTrue(all("verify with each place" in r.reason for r in rows))


class PriceRuleTests(APITestCase):
    def setUp(self):
        super().setUp()
        self.museum = make_museum()  # Indian adult 50, Foreign national 600
        self.adult, self.foreign = ticket(self.museum), ticket(self.museum, "Foreign national")
        self.day = future_open_date(self.museum)

    def test_highest_priority_matching_rule_wins(self):
        PriceRule.objects.create(museum=self.museum, name="Peak", adjustment_type="percent", value=20, priority=1)
        special = PriceRule.objects.create(museum=self.museum, name="Adult special", ticket_type=self.adult,
                                           adjustment_type="fixed_price", value=40, priority=5)
        PriceRule.objects.create(museum=self.museum, name="Off", adjustment_type="percent", value=-50, priority=9,
                                 is_active=False)
        PriceRule.objects.create(museum=self.museum, name="Other days", value=100, priority=9,
                                 weekdays=str((self.day.weekday() + 1) % 7))
        self.assertEqual(services.effective_price(self.adult, self.day), (Decimal("40.00"), special))
        self.assertEqual(services.effective_price(self.foreign, self.day)[0], Decimal("720.00"))
        # date-limited rules do not apply outside their range
        PriceRule.objects.create(museum=self.museum, name="Past", value=300, priority=20,
                                 end_date=self.day - datetime.timedelta(days=1))
        self.assertEqual(services.effective_price(self.foreign, self.day)[0], Decimal("720.00"))

    def test_booking_and_availability_use_effective_price(self):
        PriceRule.objects.create(museum=self.museum, name="Weekend", value=50, start_date=self.day, end_date=self.day)
        booking = book(make_visitor(), self.museum, visit_date=self.day, qty=2)
        self.assertEqual(booking.total_amount, Decimal("150.00"))
        self.assertEqual(booking.items.get().unit_price, Decimal("75.00"))
        r = client_for().get(f"/api/museums/{self.museum.slug}/availability/", {"date": str(self.day)})
        adult = next(p for p in r.data["prices"] if p["ticket_type"] == self.adult.id)
        self.assertEqual((adult["price"], adult["rule"]), (Decimal("75.00"), "Weekend"))
        r = client_for().get(f"/api/museums/{self.museum.slug}/prices/", {"date": str(self.day + datetime.timedelta(days=1))})
        adult = next(p for p in r.data["prices"] if p["ticket_type"] == self.adult.id)
        self.assertEqual((adult["price"], adult["rule"]), (Decimal("50.00"), None))

    def test_group_discount_applies_on_top_of_rule_price(self):
        PriceRule.objects.create(museum=self.museum, name="Peak", value=100)
        booking = services.create_booking(
            user=make_visitor(), museum=self.museum, slot=first_slot(self.museum), visit_date=self.day,
            items=[{"ticket_type": self.adult, "quantity": 25}], visitor_name="T",
            group_type="tour_operator", organisation_name="Tours",
        )
        self.assertEqual(booking.total_amount + booking.discount_amount, Decimal("2500.00"))
        self.assertEqual(booking.discount_amount, Decimal("250"))

    def test_admin_api(self):
        admin, staff = make_admin(), make_staff(self.museum)
        body = {"museum": self.museum.slug, "name": "Sunday rush", "weekdays": "6, 5,6", "adjustment_type": "percent",
                "value": "25", "priority": 2}
        self.assertEqual(client_for(staff).post("/api/admin/price-rules/", body, format="json").status_code, 403)
        r = client_for(admin).post("/api/admin/price-rules/", body, format="json")
        self.assertEqual(r.status_code, 201, r.data)
        self.assertEqual(r.data["weekdays"], "5,6")
        self.assertEqual(len(client_for(staff).get("/api/admin/price-rules/", {"museum": self.museum.slug}).data), 1)
        other_ticket = ticket(make_museum())
        for bad in ({"weekdays": "7"}, {"ticket_type": other_ticket.id}, {"adjustment_type": "fixed_price", "value": "-1"},
                    {"start_date": str(self.day), "end_date": str(self.day - datetime.timedelta(days=1))}):
            r = client_for(admin).post("/api/admin/price-rules/", {**body, **bad}, format="json")
            self.assertEqual(r.status_code, 400, bad)


class FacilitiesAndCrowdTests(APITestCase):
    def setUp(self):
        super().setUp()
        self.museum = make_museum(slots=[(datetime.time(10), datetime.time(11), 10), (datetime.time(14), datetime.time(15), 10)])

    def test_admin_saves_facilities_with_validation(self):
        url = f"/api/museums/{self.museum.slug}/"
        good = {"wheelchair": True, "photography": "no_flash", "avg_visit_minutes": "90", "nearest_metro": " Central ", "lift": None}
        r = client_for(make_admin()).patch(url, {"facilities": good}, format="json")
        self.assertEqual(r.status_code, 200, r.data)
        self.assertEqual(r.data["facilities"], {"wheelchair": True, "photography": "no_flash", "avg_visit_minutes": 90, "nearest_metro": "Central"})
        self.assertEqual(client_for().get(url).data["facilities"]["photography"], "no_flash")
        for bad in ({"wheelchair": "yes"}, {"photography": "sometimes"}, {"spa": True}, {"avg_visit_minutes": 0}):
            self.assertEqual(client_for(make_admin()).patch(url, {"facilities": bad}, format="json").status_code, 400, bad)

    def test_crowd_levels(self):
        from museums.views import crowd_level

        self.assertEqual([crowd_level(n, 100) for n in (0, 39, 40, 74, 75, 99, 100, 120)],
                         ["quiet", "quiet", "moderate", "moderate", "busy", "busy", "full", "full"])

    def test_availability_reports_crowd_and_entered_today(self):
        day = future_open_date(self.museum, 2)
        slot10, _ = self.museum.slots.order_by("start_time")
        with frozen_now(at(day, 9, 0)):
            b = book(make_visitor(), self.museum, slot10, day, qty=8, confirm=True)
            services.mark_checked_in(b, make_staff(self.museum), admitted=3)
            r = client_for().get(f"/api/museums/{self.museum.slug}/availability/", {"date": str(day)})
            first, second = r.data["slots"]
            self.assertEqual((first["crowd"], first["entered_so_far"]), ("busy", 3))
            self.assertEqual((second["crowd"], second["entered_so_far"]), ("quiet", 0))
        r = client_for().get(f"/api/museums/{self.museum.slug}/availability/", {"date": str(day)})
        self.assertNotIn("entered_so_far", r.data["slots"][0])  # only reported for today


class ExtraPhotoTests(APITestCase):
    """fetch_more_photos tops a place up to MAX_PHOTOS without touching hand-added photos."""

    @staticmethod
    def photo(n):
        return {"url": f"https://upload.wikimedia.org/x/{n}.jpg", "credit": f"Photo {n}", "source_url": "", "caption": ""}

    def test_tops_up_without_duplicates_and_respects_the_limit(self):
        from museums import wikipedia

        museum = make_museum()
        museum.image_url = ""
        museum.save()
        MuseumImage.objects.create(museum=museum, url="https://example.com/own.jpg", sort_order=0)
        photos = [self.photo(n) for n in range(20)] + [self.photo(3)]

        added = wikipedia.apply_extra_photos(museum, photos)

        museum.refresh_from_db()
        self.assertEqual(museum.image_url, photos[0]["url"])  # first photo becomes the main one
        self.assertEqual(1 + museum.images.count(), wikipedia.MAX_PHOTOS)
        self.assertEqual(added, wikipedia.MAX_PHOTOS - 1)
        self.assertTrue(museum.images.filter(url="https://example.com/own.jpg").exists())
        self.assertEqual(wikipedia.apply_extra_photos(museum, photos), 0)  # re-running adds nothing

    def test_photo_credits_are_short_and_readable(self):
        from museums.wikipedia import clean_artist, tidy_credit

        self.assertEqual(
            clean_artist("No machine-readable author provided. Faide~commonswiki assumed (based on copyright claims)."),
            "Faide",
        )
        self.assertEqual(clean_artist("Statue: Biswarup Ganguly\n\nBackground: Gary Todd"), "Statue: Biswarup Ganguly; Background: Gary Todd")
        self.assertEqual(clean_artist("This Image was created by User:PlaneMad.\nIf you are using the image…"), "PlaneMad")
        self.assertLessEqual(len(clean_artist("word " * 60)), 81)
        self.assertEqual(clean_artist(""), "Unknown author")
        self.assertEqual(
            tidy_credit("Photo: A.h.longhurst\n\nPublication date 1938, Public domain, via Wikimedia Commons"),
            "Photo: A.h.longhurst; Publication date 1938, Public domain, via Wikimedia Commons",
        )
        self.assertEqual(tidy_credit("My own photo"), "My own photo")


# ------------------------------------------------------------------ review photos, virtual tours

from unittest import mock  # noqa: E402

from museums.models import REVIEW_PHOTO_MAX_PER_REVIEW, ReviewPhoto  # noqa: E402


class ReviewPhotoTests(APITestCase):
    def setUp(self):
        super().setUp()
        self.media = tempfile.mkdtemp(prefix="aa-test-media-")
        self.addCleanup(shutil.rmtree, self.media, ignore_errors=True)
        override = override_settings(MEDIA_ROOT=self.media)
        override.enable()
        self.addCleanup(override.disable)
        self.museum = make_museum()
        self.visitor = make_visitor(first_name="Kiran", last_name="Patel")
        book(self.visitor, self.museum, visit_date=timezone.localdate() - datetime.timedelta(days=3), confirm=True)
        self.client = client_for(self.visitor)
        self.reviews_url = f"/api/museums/{self.museum.slug}/reviews/"
        self.url = self.reviews_url + "photos/"
        r = self.client.post(self.reviews_url, {"rating": 4.5, "title": "Lovely"}, format="json")
        self.assertEqual(r.status_code, 201, r.data)
        self.review = Review.objects.get(user=self.visitor)

    image = staticmethod(PhotoUploadTests.image)

    def upload(self, *files, client=None):
        return (client or self.client).post(self.url, {"file": list(files) or [self.image()]}, format="multipart")

    def test_owner_uploads_pending_photo(self):
        r = self.upload(self.image("JPEG", "a.jpg"), self.image("WEBP", "b.webp"))
        self.assertEqual(r.status_code, 201, r.data)
        self.assertEqual([p["status"] for p in r.data], ["pending", "pending"])
        self.assertTrue(r.data[0]["url"].endswith(".jpg"))
        self.assertTrue(r.data[1]["url"].endswith(".webp"))
        self.assertTrue(Path(self.media, "reviews").exists())
        # Rating is untouched by photos
        self.review.refresh_from_db()
        self.assertEqual(self.review.rating, Decimal("4.5"))

    def test_upload_requires_own_review_and_login(self):
        self.assertEqual(self.upload(client=client_for()).status_code, 401)
        r = self.upload(client=client_for(make_visitor()))
        self.assertEqual(r.status_code, 400)
        self.assertIn("review first", str(r.data))

    def test_type_and_size_checks(self):
        fake = SimpleUploadedFile("evil.jpg", b"<?php echo 1; ?>", content_type="image/jpeg")
        r = self.upload(fake)
        self.assertEqual(r.status_code, 400)
        self.assertIn("not a readable image", str(r.data["file"]))
        r = self.upload(self.image("GIF", "a.gif"))
        self.assertIn("Only JPG", str(r.data["file"]))
        with mock.patch("museums.views.REVIEW_PHOTO_MAX_MB", 0):
            r = self.upload()
        self.assertEqual(r.status_code, 400)
        self.assertIn("MB or smaller", str(r.data["file"]))
        self.assertFalse(ReviewPhoto.objects.exists())

    def test_max_four_photos_rejected_ones_do_not_count(self):
        r = self.upload(*[self.image() for _ in range(REVIEW_PHOTO_MAX_PER_REVIEW + 1)])
        self.assertEqual(r.status_code, 400)
        self.assertFalse(ReviewPhoto.objects.exists())
        self.assertEqual(self.upload(*[self.image() for _ in range(REVIEW_PHOTO_MAX_PER_REVIEW)]).status_code, 201)
        self.assertEqual(self.upload().status_code, 400)
        ReviewPhoto.objects.filter(pk=ReviewPhoto.objects.first().pk).update(status=ReviewPhoto.Status.REJECTED)
        self.assertEqual(self.upload().status_code, 201)

    def test_moderation_and_public_visibility(self):
        self.upload(self.image(), self.image())
        first, second = ReviewPhoto.objects.order_by("id")
        # Public sees nothing yet; the owner sees both as waiting for approval
        public = client_for().get(self.reviews_url).data
        self.assertEqual(public["results"][0]["photos"], [])
        self.assertEqual(public["visitor_photos"], [])
        mine = self.client.get(self.reviews_url).data["my_review"]
        self.assertEqual([p["status_label"] for p in mine["photos"]], ["Waiting for approval"] * 2)

        admin = client_for(make_admin())
        r = admin.get("/api/admin/reviews/", {"has_pending_photos": "true"})
        self.assertEqual([x["id"] for x in results(r)], [self.review.id])
        self.assertEqual(len(results(r)[0]["photos"]), 2)
        mod_url = f"/api/admin/reviews/{self.review.id}/photos/"
        self.assertEqual(admin.patch(mod_url + f"{first.id}/", {"status": "approved"}, format="json").status_code, 200)
        self.assertEqual(admin.patch(mod_url + f"{second.id}/", {"status": "rejected"}, format="json").status_code, 200)
        self.assertEqual(admin.patch(mod_url + f"{second.id}/", {"status": "nope"}, format="json").status_code, 400)
        self.assertEqual(client_for(self.visitor).patch(mod_url + f"{first.id}/", {"status": "approved"},
                                                        format="json").status_code, 403)
        self.assertEqual(results(admin.get("/api/admin/reviews/", {"has_pending_photos": "true"})), [])

        public = client_for().get(self.reviews_url).data
        self.assertEqual([p["id"] for p in public["results"][0]["photos"]], [first.id])
        self.assertEqual([p["id"] for p in public["visitor_photos"]], [first.id])
        self.assertEqual(public["visitor_photos"][0]["user_name"], "Kiran P.")
        # The owner no longer sees the rejected one
        mine = self.client.get(self.reviews_url).data["my_review"]
        self.assertEqual([p["id"] for p in mine["photos"]], [first.id])
        # A hidden review hides its photos too
        Review.objects.filter(pk=self.review.pk).update(is_published=False)
        self.assertEqual(client_for().get(self.reviews_url).data["visitor_photos"], [])

    def test_owner_deletes_photo_and_file(self):
        self.upload()
        photo = ReviewPhoto.objects.get()
        path = Path(photo.image.path)
        self.assertTrue(path.exists())
        other = client_for(make_visitor())
        self.assertEqual(other.delete(f"{self.url}{photo.id}/").status_code, 404)
        self.assertEqual(self.client.delete(f"{self.url}{photo.id}/").status_code, 204)
        self.assertFalse(ReviewPhoto.objects.exists())
        self.assertFalse(path.exists())


class VirtualTourTests(APITestCase):
    def setUp(self):
        super().setUp()
        self.museum = make_museum()
        self.url = f"/api/museums/{self.museum.slug}/"
        self.admin = client_for(make_admin())

    def test_field_in_detail_and_kind_guessed(self):
        r = client_for().get(self.url)
        self.assertEqual((r.data["virtual_tour_url"], r.data["virtual_tour_kind"]), ("", ""))
        cases = {
            "https://www.youtube.com/watch?v=abc123": "video",
            "https://www.google.com/maps/@?api=1&map_action=pano&viewpoint=27.1751,78.0421": "google_street_view",
            "https://artsandculture.google.com/story/abc": "360",
            "https://example.org/tour": "other",
        }
        for url, kind in cases.items():
            r = self.admin.patch(self.url, {"virtual_tour_url": url}, format="json")
            self.assertEqual(r.status_code, 200, r.data)
            self.assertEqual(r.data["virtual_tour_kind"], kind, url)
        r = self.admin.patch(self.url, {"virtual_tour_url": "https://example.org/x", "virtual_tour_kind": "360"},
                             format="json")
        self.assertEqual(r.data["virtual_tour_kind"], "360")
        r = self.admin.patch(self.url, {"virtual_tour_url": ""}, format="json")
        self.assertEqual((r.data["virtual_tour_url"], r.data["virtual_tour_kind"]), ("", ""))

    def test_validation(self):
        r = self.admin.patch(self.url, {"virtual_tour_url": "not a url"}, format="json")
        self.assertEqual(r.status_code, 400)
        r = self.admin.patch(self.url, {"virtual_tour_url": "https://x.org", "virtual_tour_kind": "vr"}, format="json")
        self.assertEqual(r.status_code, 400)
        self.assertEqual(client_for(make_visitor()).patch(self.url, {"virtual_tour_url": "https://x.org"},
                                                          format="json").status_code, 403)

    def test_seed_command_sets_known_places_only(self):
        taj = make_museum("Taj Mahal")
        Museum.objects.filter(pk=taj.pk).update(slug="taj-mahal-agra")
        out = io.StringIO()
        call_command("seed_virtual_tours", stdout=out)
        taj.refresh_from_db()
        self.assertEqual(taj.virtual_tour_kind, "google_street_view")
        self.assertIn("map_action=pano", taj.virtual_tour_url)
        self.museum.refresh_from_db()
        self.assertEqual(self.museum.virtual_tour_url, "")
        Museum.objects.filter(pk=taj.pk).update(virtual_tour_url="https://example.org/own")
        call_command("seed_virtual_tours", stdout=out)
        taj.refresh_from_db()
        self.assertEqual(taj.virtual_tour_url, "https://example.org/own")  # admin's link kept without --force


class FetchCoordinatesTests(APITestCase):
    """fetch_coordinates: sanity filter, source order and apply-from-cache, with all HTTP mocked."""

    def setUp(self):
        super().setUp()
        from museums.management.commands import fetch_coordinates as fc

        self.fc = fc
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        patches = [
            mock.patch.object(fc, "CACHE_PATH", self.tmp / "coordinates_cache.json"),
            mock.patch.object(fc.wikipedia, "load_cache", return_value={}),
            mock.patch.object(fc.time, "sleep"),
            mock.patch.object(fc, "MANUAL", {}),
            mock.patch.object(fc, "ALT_NAMES", {}),
            mock.patch.object(fc, "CITY_CENTRES", {}),
        ]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)
        self.state = make_state("Rajasthan", "RJ")
        self.jaipur = make_city(self.state, "Jaipur")
        self.amber = make_museum("Amber Fort", city=self.jaipur)
        self.museum = make_museum("Jaipur City Museum", city=self.jaipur)

    def run_command(self, *args):
        out = io.StringIO()
        call_command("fetch_coordinates", *args, stdout=out, stderr=io.StringIO())
        return out.getvalue()

    def test_sanity_filter(self):
        jaipur = (26.91, 75.79)
        self.assertIsNone(self.fc.sanity_error(26.9855, 75.8513, jaipur))       # Amber Fort, 11 km
        self.assertIn("outside India", self.fc.sanity_error(51.5, -0.12, jaipur))
        self.assertIn("outside India", self.fc.sanity_error(26.9, 98.0, None))  # east of the box
        self.assertIn("km from the city centre", self.fc.sanity_error(28.6562, 77.241, jaipur))  # Delhi, ~240 km
        self.assertIsNone(self.fc.sanity_error(28.6562, 77.241, None))           # unknown centre: box only
        self.assertEqual(self.fc.sanity_error("x", 1, None), "not a number")

    def wiki_response(self, params):
        self.assertLessEqual(len(params["titles"].split("|")), 50)
        return {"query": {
            "redirects": [{"from": "Amber Fort", "to": "Amer Fort"}],
            "pages": [{"title": "Amer Fort", "coordinates": [{"lat": 26.9855, "lon": 75.8513, "primary": True}]}],
        }}

    def test_fetch_uses_wikipedia_then_nominatim_and_rejects_bad_points(self):
        wiki = {"Amber Fort|Jaipur": {"title": "Amber Fort"}}
        answers = {
            "Jaipur, Rajasthan, India": [{"lat": "26.9124", "lon": "75.7873", "class": "place", "type": "city"}],
            # first search hits a namesake far away (rejected), the second variant is right
            "Jaipur City Museum, Jaipur, Rajasthan, India": [{"lat": "19.07", "lon": "72.87", "class": "tourism", "type": "museum"}],
        }
        self.museum.name = "Jaipur City Museum (Old Hall)"
        self.museum.save()
        answers["Jaipur City Museum (Old Hall), Jaipur, Rajasthan, India"] = []
        answers["Old Hall, Jaipur, Rajasthan, India"] = [{"lat": "26.92", "lon": "75.82", "class": "tourism", "type": "museum"}]
        calls = []

        def nominatim_get(query):
            calls.append(query)
            return answers.get(query, [])

        with mock.patch.object(self.fc.wikipedia, "load_cache", return_value=wiki), \
                mock.patch.object(self.fc.wikipedia, "_get", side_effect=self.wiki_response), \
                mock.patch.object(self.fc, "nominatim_get", side_effect=nominatim_get), \
                mock.patch.object(self.fc, "wikidata_get", return_value={}):
            out = self.run_command("--fetch")
        self.amber.refresh_from_db()
        self.museum.refresh_from_db()
        self.assertEqual((float(self.amber.latitude), float(self.amber.longitude)), (26.9855, 75.8513))
        self.assertEqual((float(self.museum.latitude), float(self.museum.longitude)), (26.92, 75.82))
        self.assertIn("wikipedia: 1", out)
        self.assertIn("nominatim: 1", out)
        self.assertIn("km from the city centre", out)  # the Mumbai namesake was rejected and reported
        # everything is cached: applying again needs no network and asks nothing twice
        cache = self.fc.load_cache()
        self.assertEqual(cache["places"]["Amber Fort|Jaipur"]["source"], "wikipedia")
        Museum.objects.update(latitude=None, longitude=None)
        with mock.patch.object(self.fc, "nominatim_get", side_effect=AssertionError("no network")), \
                mock.patch.object(self.fc.wikipedia, "_get", side_effect=AssertionError("no network")):
            self.run_command()
        self.assertEqual(Museum.objects.filter(latitude__isnull=False).count(), 2)
        self.assertEqual(len(calls), len(set(calls)))

    def write_cache(self, places):
        applied = self.fc.load_cache()["applied"]  # what earlier runs wrote stays the command's own
        self.fc.save_cache({"cities": {"Jaipur|Rajasthan": {"lat": 26.9124, "lng": 75.7873}}, "places": places,
                            "wikipedia": {}, "nominatim": {}, "applied": applied})

    def test_apply_keeps_hand_entered_unless_force_and_rechecks_cache(self):
        self.write_cache({
            "Amber Fort|Jaipur": {"lat": 26.9855, "lng": 75.8513, "source": "wikipedia"},
            "Jaipur City Museum|Jaipur": {"lat": 40.0, "lng": -3.0, "source": "nominatim"},  # bad entry
        })
        Museum.objects.filter(pk=self.amber.pk).update(latitude=Decimal("26.900000"), longitude=Decimal("75.800000"))
        out = self.run_command()
        self.amber.refresh_from_db()
        self.assertEqual(self.amber.latitude, Decimal("26.900000"))  # admin's value kept
        self.assertIn("hand-entered (kept): 1", out)
        self.museum.refresh_from_db()
        self.assertIsNone(self.museum.latitude)                       # cached point outside India refused
        self.assertIn("outside India", out)
        self.run_command("--force")
        self.amber.refresh_from_db()
        self.assertEqual(self.amber.latitude, Decimal("26.985500"))
        # once written by the command, a later cache update may replace it without --force
        self.write_cache({"Amber Fort|Jaipur": {"lat": 26.9856, "lng": 75.8514, "source": "wikipedia"}})
        self.run_command()
        self.amber.refresh_from_db()
        self.assertEqual(self.amber.latitude, Decimal("26.985600"))

    def test_manual_positions_win(self):
        self.write_cache({"Amber Fort|Jaipur": {"lat": 26.9855, "lng": 75.8513, "source": "wikipedia"}})
        with mock.patch.object(self.fc, "MANUAL", {"Amber Fort|Jaipur": (26.98, 75.85)}):
            out = self.run_command()
        self.amber.refresh_from_db()
        self.assertEqual((self.amber.latitude, self.amber.longitude), (Decimal("26.980000"), Decimal("75.850000")))
        self.assertIn("manual: 1", out)


class ReviewHelpfulVoteTests(APITestCase):
    """Helpful votes: logged-in only, not on your own review, idempotent, counted atomically, sortable."""

    def setUp(self):
        super().setUp()
        self.museum = make_museum("Vote Museum")
        self.author = make_visitor()
        self.voter = make_visitor()
        self.review = Review.objects.create(museum=self.museum, user=self.author, rating=4, comment="Lovely")
        self.url = f"/api/museums/{self.museum.slug}/reviews/{self.review.id}/helpful/"

    def count(self):
        self.review.refresh_from_db()
        return self.review.helpful_count

    def test_logged_out_cannot_vote(self):
        self.assertEqual(client_for().post(self.url).status_code, 401)
        self.assertEqual(self.count(), 0)

    def test_vote_is_idempotent_and_undo(self):
        c = client_for(self.voter)
        r = c.post(self.url)
        self.assertEqual(r.status_code, 200, r.data)
        self.assertEqual(r.data, {"id": self.review.id, "helpful_count": 1, "voted_by_me": True})
        self.assertEqual(c.post(self.url).data["helpful_count"], 1)  # second POST changes nothing
        self.assertEqual(self.review.votes.count(), 1)
        client_for(make_visitor()).post(self.url)
        self.assertEqual(self.count(), 2)
        r = c.delete(self.url)
        self.assertEqual(r.data, {"id": self.review.id, "helpful_count": 1, "voted_by_me": False})
        self.assertEqual(c.delete(self.url).data["helpful_count"], 1)  # second DELETE changes nothing
        self.assertEqual(self.count(), 1)

    def test_not_on_own_review(self):
        self.assertEqual(client_for(self.author).post(self.url).status_code, 403)
        self.assertEqual(self.count(), 0)

    def test_hidden_or_other_place_review_is_404(self):
        other = make_museum()
        url = f"/api/museums/{other.slug}/reviews/{self.review.id}/helpful/"
        self.assertEqual(client_for(self.voter).post(url).status_code, 404)
        Review.objects.filter(pk=self.review.pk).update(is_published=False)
        self.assertEqual(client_for(self.voter).post(self.url).status_code, 404)

    def test_deleting_voter_lowers_count(self):
        client_for(self.voter).post(self.url)
        self.assertEqual(self.count(), 1)
        self.voter.delete()
        self.assertEqual(self.count(), 0)

    def test_sort_helpful_and_voted_by_me(self):
        older = Review.objects.create(museum=self.museum, user=make_visitor(), rating=3, comment="Old")
        Review.objects.filter(pk=older.pk).update(created_at=timezone.now() - datetime.timedelta(days=5))
        newest = Review.objects.create(museum=self.museum, user=make_visitor(), rating=5, comment="New")
        for _ in range(2):
            client_for(make_visitor()).post(f"/api/museums/{self.museum.slug}/reviews/{older.id}/helpful/")
        client_for(self.voter).post(self.url)

        base = f"/api/museums/{self.museum.slug}/reviews/"
        ids = [r["id"] for r in client_for().get(base, {"sort": "helpful"}).data["results"]]
        self.assertEqual(ids, [older.id, self.review.id, newest.id])  # 2 votes, 1 vote, 0 votes
        ids = [r["id"] for r in client_for().get(base).data["results"]]
        self.assertEqual(ids[0], newest.id)  # default is still newest first

        mine = {r["id"]: r for r in client_for(self.voter).get(base, {"sort": "helpful"}).data["results"]}
        self.assertTrue(mine[self.review.id]["voted_by_me"])
        self.assertFalse(mine[older.id]["voted_by_me"])
        self.assertEqual(mine[older.id]["helpful_count"], 2)
        anon = client_for().get(base).data["results"]
        self.assertFalse(any(r["voted_by_me"] for r in anon))


@override_settings(GOOGLE_MAPS_API_KEY="test-key")
class GooglePhotoTests(APITestCase):
    """Google Maps photos for places without their own (Google's API is faked; no network)."""

    def setUp(self):
        super().setUp()
        from django.core.cache import cache

        cache.clear()
        self.museum = make_museum("Wood Museum and Interpretation Centre")
        Museum.objects.filter(pk=self.museum.pk).update(image_url="", latitude=12.97, longitude=77.59)
        self.museum.refresh_from_db()

    def fake_api(self, path, *, body=None, fields=None, params=None):
        self.calls.append(path)
        if path == "places:searchText":
            return {"places": [
                {"id": "other", "displayName": {"text": "Some Cafe"}, "location": {"latitude": 12.97, "longitude": 77.59},
                 "photos": [{"name": "x"}]},
                {"id": "far", "displayName": {"text": "Wood Museum"}, "location": {"latitude": 19.0, "longitude": 72.8},
                 "photos": [{"name": "x"}]},
                {"id": "good", "displayName": {"text": "Wood Museum & Interpretation Centre"},
                 "location": {"latitude": 12.98, "longitude": 77.60}, "photos": [{"name": "x"}]},
            ]}
        if path.endswith("/media"):
            return {"photoUri": f"https://lh3.googleusercontent.com/{path}"}
        return {"photos": [
            {"name": "places/good/photos/a", "authorAttributions": [{"displayName": "Asha R", "uri": "https://maps.google.com/a"}]},
            {"name": "places/good/photos/b", "authorAttributions": [{"displayName": "Vik", "uri": "https://maps.google.com/v"}]},
        ]}

    def patch(self):
        from unittest import mock

        self.calls = []
        return mock.patch("museums.google_places._call", side_effect=self.fake_api)

    def test_match_needs_the_name_and_a_nearby_location(self):
        from museums import google_places

        with self.patch():
            self.assertEqual(google_places.find_place(self.museum)["id"], "good")

    def test_place_without_photo_shows_google_photos_with_credits(self):
        Museum.objects.filter(pk=self.museum.pk).update(google_place_id="good")
        with self.patch():
            listing = results(client_for().get("/api/museums/"))
            card = next(m for m in listing if m["slug"] == self.museum.slug)
            self.assertTrue(card["image_url"].endswith(f"/api/museums/{self.museum.slug}/google-photo/0/"))
            self.assertEqual(card["photo_source"], "google")
            self.assertEqual(self.calls, [])  # the list never calls Google

            detail = client_for().get(f"/api/museums/{self.museum.slug}/").data
            self.assertEqual(detail["image_credit"], "Photo: Asha R, Google Maps")
            self.assertEqual([i["credit"] for i in detail["images"]], ["Photo: Vik, Google Maps"])

            r = client_for().get(f"/api/museums/{self.museum.slug}/google-photo/1/")
            self.assertEqual(r.status_code, 302)
            self.assertEqual(r["Location"], "https://lh3.googleusercontent.com/places/good/photos/b/media")
            self.assertEqual(client_for().get(f"/api/museums/{self.museum.slug}/google-photo/5/").status_code, 404)

    def test_own_photo_wins_and_admin_save_keeps_google_link_out(self):
        Museum.objects.filter(pk=self.museum.pk).update(google_place_id="good")
        url = f"/api/museums/{self.museum.slug}/"
        with self.patch():
            shown = client_for().get(url).data["image_url"]
            r = client_for(make_admin()).patch(url, {"image_url": shown}, format="json")
        self.assertEqual(r.status_code, 200, r.data)
        self.museum.refresh_from_db()
        self.assertEqual(self.museum.image_url, "")
        Museum.objects.filter(pk=self.museum.pk).update(image_url="https://upload.wikimedia.org/x.jpg")
        self.assertEqual(client_for().get(url).data["image_url"], "https://upload.wikimedia.org/x.jpg")

    @override_settings(GOOGLE_MAPS_API_KEY="")
    def test_nothing_changes_without_a_key(self):
        Museum.objects.filter(pk=self.museum.pk).update(google_place_id="good")
        self.assertEqual(client_for().get(f"/api/museums/{self.museum.slug}/").data["image_url"], "")
        self.assertEqual(client_for().get(f"/api/museums/{self.museum.slug}/google-photo/0/").status_code, 404)
