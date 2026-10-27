"""Ticket add-ons: public list, choosing them at checkout (pricing, limits, daily stock), permissions, admin CRUD."""
from decimal import Decimal
from io import StringIO

from django.core.management import call_command

from addons.models import AddOn
from bookings import services
from bookings.models import Booking
from bookings.tests.factories import (
    APITestCase, age_booking, book, client_for, future_open_date, make_admin, make_museum, make_staff, make_visitor,
)
from museums.models import Museum
from promotions.models import PromoCode


def make_addon(museum, name="Audio guide", kind=AddOn.Kind.AUDIO_GUIDE, price="150", per=AddOn.Per.PERSON, **extra):
    return AddOn.objects.create(museum=museum, name=name, kind=kind, price=Decimal(price), per=per, **extra)


class AddOnBase(APITestCase):
    def setUp(self):
        super().setUp()
        self.museum = make_museum()  # Indian adult ₹50, Foreign national ₹600
        self.audio = make_addon(self.museum)
        self.camera = make_addon(self.museum, "Camera permit", AddOn.Kind.CAMERA, "50", AddOn.Per.BOOKING, max_per_booking=2)
        self.wheelchair = make_addon(self.museum, "Wheelchair", AddOn.Kind.WHEELCHAIR, "0", AddOn.Per.BOOKING, daily_stock=1)
        self.visitor = make_visitor()
        self.client = client_for(self.visitor)
        self.booking = book(self.visitor, self.museum, qty=2)  # 2 x ₹50, pending

    def choose(self, *items, booking=None, client=None):
        booking = booking or self.booking
        return (client or self.client).post(
            f"/api/bookings/{booking.reference}/addons/",
            {"items": [{"addon": a.id, "quantity": q} for a, q in items]}, format="json",
        )


class PublicAddOnTests(AddOnBase):
    def test_lists_active_addons_with_icons(self):
        make_addon(self.museum, "Old tour", AddOn.Kind.GUIDED_TOUR, is_active=False)
        r = client_for().get(f"/api/museums/{self.museum.slug}/addons/")
        self.assertEqual(r.status_code, 200)
        self.assertEqual([a["name"] for a in r.data], ["Audio guide", "Camera permit", "Wheelchair"])
        self.assertEqual(r.data[0]["icon"], "headphones")
        self.assertEqual(r.data[0]["per"], "person")
        self.assertIsNone(r.data[2]["remaining"])  # no date asked

    def test_remaining_stock_for_a_date(self):
        self.choose((self.wheelchair, 1))
        day = self.booking.visit_date
        r = client_for().get(f"/api/museums/{self.museum.slug}/addons/", {"date": str(day)})
        self.assertEqual(r.data[2]["remaining"], 0)
        # The owner's own booking does not count against itself.
        r = self.client.get(f"/api/museums/{self.museum.slug}/addons/", {"date": str(day), "booking": self.booking.reference})
        self.assertEqual(r.data[2]["remaining"], 1)

    def test_unknown_place_404(self):
        self.assertEqual(client_for().get("/api/museums/nowhere/addons/").status_code, 404)


class ChooseAddOnTests(AddOnBase):
    def test_pricing_per_person_and_per_booking(self):
        r = self.choose((self.audio, 2), (self.camera, 1))
        self.assertEqual(r.status_code, 200, r.data)
        self.assertEqual(Decimal(r.data["addons_amount"]), Decimal("350"))
        self.assertEqual(Decimal(r.data["total_amount"]), Decimal("450"))
        self.assertEqual(Decimal(r.data["subtotal_amount"]), Decimal("100"))  # tickets only
        self.assertEqual(r.data["addons_summary"], "2 x Audio guide, 1 x Camera permit")
        self.assertEqual([a["icon"] for a in r.data["addons"]], ["headphones", "camera"])

    def test_replaces_selection_and_keeps_price_snapshot(self):
        self.choose((self.audio, 2))
        AddOn.objects.filter(pk=self.audio.pk).update(price=999)
        r = self.choose((self.camera, 1))
        self.assertEqual(r.data["addons_summary"], "1 x Camera permit")
        self.assertEqual(Decimal(r.data["total_amount"]), Decimal("150"))
        r = self.choose()
        self.assertEqual(r.data["addons"], [])
        self.assertEqual(Decimal(r.data["total_amount"]), Decimal("100"))

    def test_free_addon_does_not_change_total(self):
        r = self.choose((self.wheelchair, 1))
        self.assertEqual(r.status_code, 200, r.data)
        self.assertEqual(Decimal(r.data["total_amount"]), Decimal("100"))
        self.assertEqual(r.data["status"], "pending")

    def test_quantity_limits(self):
        self.assertEqual(self.choose((self.audio, 3)).status_code, 400)  # 2 visitors
        self.assertEqual(self.choose((self.camera, 3)).status_code, 400)  # max 2 per booking
        self.assertEqual(self.choose((self.wheelchair, 2)).status_code, 400)  # per booking, no max: 1
        self.assertEqual(self.choose((self.camera, 2)).status_code, 200)

    def test_daily_stock(self):
        self.assertEqual(self.choose((self.wheelchair, 1)).status_code, 200)
        other = make_visitor()
        second = book(other, self.museum, visit_date=self.booking.visit_date)
        r = self.choose((self.wheelchair, 1), booking=second, client=client_for(other))
        self.assertEqual(r.status_code, 400)
        self.assertIn("sold out", str(r.data))
        # Another day still has stock.
        later = book(other, self.museum, visit_date=future_open_date(self.museum, 20))
        self.assertEqual(self.choose((self.wheelchair, 1), booking=later, client=client_for(other)).status_code, 200)
        # Cancelling the first booking frees its wheelchair.
        services.cancel_booking(self.booking)
        self.assertEqual(self.choose((self.wheelchair, 1), booking=second, client=client_for(other)).status_code, 200)

    def test_expired_hold_releases_stock(self):
        self.choose((self.wheelchair, 1))
        age_booking(self.booking, 60)
        other = make_visitor()
        second = book(other, self.museum, visit_date=self.booking.visit_date)
        self.assertEqual(self.choose((self.wheelchair, 1), booking=second, client=client_for(other)).status_code, 200)

    def test_addon_of_another_place_or_inactive_rejected(self):
        elsewhere = make_addon(make_museum())
        self.assertEqual(self.choose((elsewhere, 1)).status_code, 400)
        self.audio.is_active = False
        self.audio.save()
        self.assertEqual(self.choose((self.audio, 1)).status_code, 400)

    def test_only_owner_and_only_while_pending(self):
        stranger = client_for(make_visitor())
        self.assertEqual(self.choose((self.audio, 1), client=stranger).status_code, 404)
        staff = client_for(make_staff(self.museum))
        self.assertEqual(self.choose((self.audio, 1), client=staff).status_code, 403)
        self.assertEqual(client_for().post(f"/api/bookings/{self.booking.reference}/addons/", {"items": []}, format="json").status_code, 401)
        services.confirm_payment(self.booking, Booking.PaymentMethod.UPI)
        self.assertEqual(self.choose((self.audio, 1)).status_code, 400)

    def test_promo_code_recalculated_on_total_with_addons(self):
        PromoCode.objects.create(code="TENOFF", value=10)
        r = self.client.post(f"/api/bookings/{self.booking.reference}/apply-code/", {"code": "TENOFF"})
        self.assertEqual(Decimal(r.data["promo_discount"]), Decimal("10"))
        r = self.choose((self.audio, 2))  # 100 + 300 = 400, 10% off
        self.assertEqual(Decimal(r.data["promo_discount"]), Decimal("40"))
        self.assertEqual(Decimal(r.data["total_amount"]), Decimal("360"))
        self.assertEqual(self.booking.promo_redemptions.get().amount, Decimal("40"))

    def test_promo_minimum_blocks_removing_addons(self):
        PromoCode.objects.create(code="BIG", discount_type="flat", value=50, min_order_amount=300)
        self.choose((self.audio, 2))
        self.assertEqual(self.client.post(f"/api/bookings/{self.booking.reference}/apply-code/", {"code": "BIG"}).status_code, 200)
        r = self.choose()
        self.assertEqual(r.status_code, 400)
        self.booking.refresh_from_db()
        self.assertEqual(self.booking.addons.count(), 1)  # nothing changed

    def test_gate_manifest_lists_addons(self):
        self.choose((self.audio, 2))
        services.confirm_payment(self.booking, Booking.PaymentMethod.UPI)
        staff = client_for(make_staff(self.museum))
        r = staff.get("/api/bookings/gate-manifest/", {"museum": self.museum.slug, "date": str(self.booking.visit_date)})
        ticket = r.data["tickets"][0]
        self.assertIn("2 x Audio guide", ticket["items"])
        self.assertEqual(ticket["addons_summary"], "2 x Audio guide")


class AdminAddOnTests(APITestCase):
    def setUp(self):
        super().setUp()
        self.museum = make_museum()
        self.other = make_museum()
        self.addon = make_addon(self.museum)
        make_addon(self.other, "Locker", AddOn.Kind.LOCKER, "20", AddOn.Per.BOOKING)

    def test_admin_crud(self):
        admin = client_for(make_admin())
        r = admin.post("/api/admin/addons/", {
            "museum": self.museum.slug, "name": "Parking", "kind": "parking", "price": "40", "per": "booking",
        })
        self.assertEqual(r.status_code, 201, r.data)
        self.assertEqual(r.data["icon"], "cone-striped")
        r = admin.get("/api/admin/addons/", {"museum": self.museum.slug})
        self.assertEqual([a["name"] for a in r.data], ["Audio guide", "Parking"])
        self.assertEqual(admin.patch(f"/api/admin/addons/{self.addon.id}/", {"price": "-1"}).status_code, 400)
        self.assertEqual(admin.patch(f"/api/admin/addons/{self.addon.id}/", {"museum": self.other.slug}).status_code, 400)
        self.assertEqual(admin.patch(f"/api/admin/addons/{self.addon.id}/", {"price": "120"}).status_code, 200)
        self.assertEqual(admin.delete(f"/api/admin/addons/{r.data[1]['id']}/").status_code, 204)

    def test_sold_addon_cannot_be_deleted(self):
        visitor = make_visitor()
        booking = book(visitor, self.museum)
        services.set_booking_addons(booking, [{"addon": self.addon.id, "quantity": 1}])
        r = client_for(make_admin()).delete(f"/api/admin/addons/{self.addon.id}/")
        self.assertEqual(r.status_code, 400)

    def test_staff_read_only_for_assigned_places(self):
        staff = client_for(make_staff(self.museum))
        r = staff.get("/api/admin/addons/")
        self.assertEqual([a["museum"] for a in r.data], [self.museum.slug])
        self.assertEqual(staff.get("/api/admin/addons/", {"museum": self.other.slug}).data, [])
        self.assertEqual(staff.patch(f"/api/admin/addons/{self.addon.id}/", {"price": "1"}).status_code, 403)
        self.assertEqual(staff.post("/api/admin/addons/", {"museum": self.museum.slug, "name": "X"}).status_code, 403)
        self.assertEqual(client_for(make_visitor()).get("/api/admin/addons/").status_code, 403)


class SeedAddOnsTests(APITestCase):
    def test_seed_is_idempotent_and_priced_by_place_type(self):
        museum = make_museum(place_type=Museum.PlaceType.MUSEUM)
        fort = make_museum(place_type=Museum.PlaceType.FORT, is_featured=True)
        call_command("seed_addons", stdout=StringIO())
        call_command("seed_addons", stdout=StringIO())
        kinds = set(museum.addons.values_list("kind", flat=True))
        self.assertEqual(kinds, {"audio_guide", "camera", "video", "locker", "wheelchair"})
        self.assertEqual(fort.addons.get(kind="guided_tour").price, Decimal("600"))
        self.assertEqual(fort.addons.get(kind="video").price, Decimal("500"))
        wheelchair = fort.addons.get(kind="wheelchair")
        self.assertEqual((wheelchair.price, wheelchair.daily_stock), (Decimal("0"), 5))
        self.assertEqual(AddOn.objects.filter(museum=fort, kind="camera").count(), 1)
