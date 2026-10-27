"""Heritage Card: plans, purchase (demo gateway and Razorpay + webhook), the booking discount, admin screens."""
import datetime
import json
import re
from decimal import Decimal
from io import StringIO
from unittest import mock

from django.core.management import call_command
from django.test import Client, override_settings
from django.utils import timezone

from bookings import services as booking_services
from bookings.models import Booking
from bookings.tests.factories import (
    APITestCase, PHONE, book, client_for, first_slot, future_open_date, make_admin, make_museum, make_staff,
    make_visitor, ticket,
)
from bookings.tests.test_payments import KEY_SECRET, WEBHOOK_SECRET, WEBHOOK_URL, FakeRazorpay, sign
from memberships import services
from memberships.models import Membership, MembershipPlan


def make_plan(name="Heritage Card Individual", price="1499", discount_percent=20, max_visitors=1, **extra):
    places = extra.pop("places", [])
    plan = MembershipPlan.objects.create(
        name=name, price=Decimal(price), discount_percent=discount_percent, max_visitors_per_booking=max_visitors, **extra,
    )
    plan.places.set(places)
    return plan


def make_member(user, plan, confirm=True):
    membership = services.create_membership(user=user, plan=plan, holder_name="Asha Rao")
    if confirm and membership.status == Membership.Status.PENDING:
        services.confirm_payment(membership, "upi")
    membership.refresh_from_db()
    return membership


def book_mixed(user, museum, visit_date=None, adults=1, foreign=1, **kw):
    """Indian adult (₹50) + Foreign national (₹600) tickets in one online booking."""
    items = [i for i in (
        {"ticket_type": ticket(museum), "quantity": adults},
        {"ticket_type": ticket(museum, "Foreign national"), "quantity": foreign},
    ) if i["quantity"]]
    return booking_services.create_booking(
        user=user, museum=museum, slot=first_slot(museum), visit_date=visit_date or future_open_date(museum),
        items=items, visitor_name="Asha Rao", visitor_email=user.email, visitor_phone=PHONE, **kw,
    )


class MembershipBase(APITestCase):
    def setUp(self):
        super().setUp()
        self.today = timezone.localdate()
        self.museum = make_museum()
        self.plan = make_plan()
        self.visitor = make_visitor()
        self.client = client_for(self.visitor)


class PlanTests(MembershipBase):
    def test_public_list_shows_active_plans(self):
        make_plan("Old plan", is_active=False)
        r = client_for().get("/api/membership-plans/")
        self.assertEqual(r.status_code, 200)
        self.assertEqual([p["slug"] for p in r.data], [self.plan.slug])
        self.assertTrue(r.data[0]["all_places"])
        self.assertEqual(r.data[0]["benefit_percent"], 20)

    def test_seed_command_is_idempotent(self):
        call_command("seed_memberships", stdout=StringIO())
        call_command("seed_memberships", stdout=StringIO())
        # The setUp plan has the same slug as the seeded Individual plan, so it is updated, not duplicated.
        seeded = MembershipPlan.objects.filter(slug__startswith="heritage-card-")
        self.assertEqual(seeded.count(), 3)
        self.assertEqual(MembershipPlan.objects.count(), 3)
        family = seeded.get(slug="heritage-card-family")
        self.assertEqual((family.price, family.discount_percent, family.max_visitors_per_booking), (Decimal("3999"), 25, 4))


class PurchaseTests(MembershipBase):
    def test_buy_with_demo_gateway(self):
        r = self.client.post("/api/memberships/", {"plan": self.plan.slug, "holder_name": "Asha Rao"})
        self.assertEqual(r.status_code, 201, r.data)
        self.assertEqual(r.data["status"], "pending")
        card = r.data["card_number"]
        self.assertRegex(card, r"^AAM-[A-Z2-9]{4}-[A-Z2-9]{4}$")
        self.assertIsNone(self.client.get("/api/memberships/current/").data["membership"])
        r = self.client.post(f"/api/memberships/{card}/payment-order/")
        self.assertEqual(r.data, {"provider": "mock"})
        r = self.client.post(f"/api/memberships/{card.lower()}/pay/", {"method": "upi"})
        self.assertEqual(r.status_code, 200, r.data)
        self.assertEqual(r.data["status"], "active")
        self.assertEqual(r.data["starts_on"], str(self.today))
        self.assertEqual(r.data["ends_on"], str(self.today + datetime.timedelta(days=364)))
        self.assertEqual(self.client.get("/api/memberships/current/").data["membership"]["card_number"], card)
        self.assertEqual(self.client.post(f"/api/memberships/{card}/pay/", {"method": "upi"}).status_code, 400)

    def test_login_required_and_own_cards_only(self):
        self.assertEqual(client_for().post("/api/memberships/", {"plan": self.plan.slug}).status_code, 401)
        card = make_member(self.visitor, self.plan)
        self.assertEqual(client_for(make_visitor()).get(f"/api/memberships/{card.card_number}/").status_code, 404)

    def test_inactive_plan_not_on_sale(self):
        self.plan.is_active = False
        self.plan.save()
        self.assertEqual(self.client.post("/api/memberships/", {"plan": self.plan.slug}).status_code, 400)

    def test_free_plan_active_at_once(self):
        r = self.client.post("/api/memberships/", {"plan": make_plan("Press", price="0").slug})
        self.assertEqual(r.data["status"], "active")

    def test_expired_hold_cannot_be_paid(self):
        card = make_member(self.visitor, self.plan, confirm=False)
        Membership.objects.filter(pk=card.pk).update(created_at=timezone.now() - datetime.timedelta(hours=1))
        r = self.client.post(f"/api/memberships/{card.card_number}/pay/", {"method": "upi"})
        self.assertEqual(r.status_code, 400)

    def test_early_renewal_starts_after_current_card(self):
        first = make_member(self.visitor, self.plan)
        second = make_member(self.visitor, self.plan)
        self.assertEqual(second.starts_on, first.ends_on + datetime.timedelta(days=1))


@override_settings(RAZORPAY_KEY_ID="rzp_test_x", RAZORPAY_KEY_SECRET=KEY_SECRET, RAZORPAY_WEBHOOK_SECRET=WEBHOOK_SECRET)
class RazorpayMembershipTests(MembershipBase):
    def setUp(self):
        super().setUp()
        self.fake = FakeRazorpay()
        patcher = mock.patch("bookings.payments._client", return_value=self.fake)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.card = make_member(self.visitor, self.plan, confirm=False)

    def webhook(self, event="payment.captured", **entity):
        body = json.dumps({"event": event, "payload": {entity.pop("key", "payment"): {"entity": entity}}})
        return Client().post(WEBHOOK_URL, data=body, content_type="application/json",
                             headers={"X-Razorpay-Signature": sign(body, WEBHOOK_SECRET)})

    def test_checkout_and_verified_payment(self):
        r = self.client.post(f"/api/memberships/{self.card.card_number}/payment-order/")
        self.assertEqual(r.status_code, 200, r.data)
        self.assertEqual(r.data["amount"], 149900)
        r = self.client.post(f"/api/memberships/{self.card.card_number}/pay/", {
            "razorpay_order_id": "order_TEST1", "razorpay_payment_id": "pay_1",
            "razorpay_signature": sign("order_TEST1|pay_1", KEY_SECRET)})
        self.assertEqual(r.status_code, 200, r.data)
        self.assertEqual((r.data["status"], r.data["payment_method"], r.data["gateway"]), ("active", "card", "razorpay"))

    def test_webhook_finalizes_payment_once(self):
        self.client.post(f"/api/memberships/{self.card.card_number}/payment-order/")
        self.assertEqual(self.webhook(id="pay_W1", order_id="order_TEST1", method="upi").status_code, 200)
        self.card.refresh_from_db()
        self.assertEqual((self.card.status, self.card.payment_id, self.card.payment_method), ("active", "pay_W1", "upi"))
        ends = self.card.ends_on
        self.webhook(id="pay_W1", order_id="order_TEST1", method="upi")  # repeated delivery: nothing changes
        self.card.refresh_from_db()
        self.assertEqual(self.card.ends_on, ends)

    def test_webhook_for_cancelled_card_refunds(self):
        self.client.post(f"/api/memberships/{self.card.card_number}/payment-order/")
        services.cancel_membership(self.card)
        self.webhook(id="pay_W2", order_id="order_TEST1", method="card")
        self.card.refresh_from_db()
        self.assertEqual((self.card.status, self.card.refund_status), ("cancelled", "processed"))
        self.webhook(event="refund.failed", key="refund", id="rfnd_TEST1")
        self.card.refresh_from_db()
        self.assertEqual(self.card.refund_status, "failed")

    def test_finalize_service_signature(self):
        self.client.post(f"/api/memberships/{self.card.card_number}/payment-order/")
        services.finalize_gateway_payment(self.card.pk, "pay_S1")
        self.card.refresh_from_db()
        self.assertEqual(self.card.status, "active")


class BookingBenefitTests(MembershipBase):
    def test_discount_on_most_expensive_tickets_up_to_limit(self):
        make_member(self.visitor, self.plan)  # 20%, 1 visitor
        booking = book_mixed(self.visitor, self.museum, adults=2, foreign=1)
        self.assertEqual(booking.membership_discount, Decimal("120"))  # 20% of the ₹600 ticket
        self.assertEqual(booking.total_amount, Decimal("580"))
        self.assertIsNotNone(booking.membership)

    def test_family_plan_covers_several_visitors(self):
        make_member(self.visitor, make_plan("Family", discount_percent=25, max_visitors=2))
        booking = book_mixed(self.visitor, self.museum, adults=2, foreign=1)
        self.assertEqual(booking.membership_discount, Decimal("163"))  # 25% of 600 + 50, rounded
        self.assertEqual(booking.total_amount, Decimal("537"))

    def test_free_entry_plan(self):
        make_member(self.visitor, make_plan("Patron", free_entry=True, max_visitors=2))
        booking = book_mixed(self.visitor, self.museum, adults=1, foreign=1)
        self.assertEqual(booking.total_amount, Decimal("0"))
        self.assertEqual(booking.status, Booking.Status.CONFIRMED)

    def test_shown_in_booking_api(self):
        card = make_member(self.visitor, self.plan)
        museum = make_museum(slots=[(datetime.time(10), datetime.time(11), 50)])
        day = future_open_date(museum)
        r = self.client.post("/api/bookings/", {
            "museum": museum.slug, "slot": first_slot(museum).id, "visit_date": str(day),
            "items": [{"ticket_type": ticket(museum, "Foreign national").id, "quantity": 1}],
            "visitor_name": "Asha", "visitor_email": "a@example.com", "visitor_phone": PHONE,
        }, format="json")
        self.assertEqual(r.status_code, 201, r.data)
        self.assertEqual(Decimal(r.data["membership_discount"]), Decimal("120"))
        self.assertEqual(r.data["membership_card"], card.card_number)
        self.assertEqual(Decimal(r.data["subtotal_amount"]), Decimal("600"))

    def test_expired_membership_gives_no_discount(self):
        card = make_member(self.visitor, self.plan)
        visit = future_open_date(self.museum)
        Membership.objects.filter(pk=card.pk).update(ends_on=visit - datetime.timedelta(days=1))
        booking = book_mixed(self.visitor, self.museum, visit_date=visit)
        self.assertEqual(booking.membership_discount, Decimal("0"))
        self.assertIsNone(booking.membership)
        # Past its last day the nightly/lazy expiry marks it expired too.
        Membership.objects.filter(pk=card.pk).update(ends_on=self.today - datetime.timedelta(days=1))
        services.expire_stale()
        card.refresh_from_db()
        self.assertEqual(card.status, Membership.Status.EXPIRED)
        self.assertEqual(book_mixed(self.visitor, self.museum).membership_discount, Decimal("0"))

    def test_pending_or_cancelled_card_gives_no_discount(self):
        make_member(self.visitor, self.plan, confirm=False)
        self.assertEqual(book_mixed(self.visitor, self.museum).membership_discount, Decimal("0"))
        card = make_member(self.visitor, self.plan)
        services.cancel_membership(card)
        self.assertEqual(book_mixed(self.visitor, self.museum).membership_discount, Decimal("0"))

    def test_only_at_plan_places(self):
        make_member(self.visitor, make_plan("Delhi only", places=[make_museum()]))
        self.assertEqual(book_mixed(self.visitor, self.museum).membership_discount, Decimal("0"))

    def test_no_discount_for_group_or_counter_sales(self):
        make_member(self.visitor, self.plan)
        group = booking_services.create_booking(
            user=self.visitor, museum=self.museum, slot=first_slot(self.museum), visit_date=future_open_date(self.museum),
            items=[{"ticket_type": ticket(self.museum), "quantity": 25}], visitor_name="School", group_type="school",
            organisation_name="DPS",
        )
        self.assertEqual(group.membership_discount, Decimal("0"))
        staff = make_staff(self.museum)
        make_member(staff, self.plan)
        counter = book(staff, self.museum, channel=Booking.Channel.COUNTER, payment_method=Booking.PaymentMethod.CASH,
                       visit_date=self.today, slot=self.museum.slots.order_by("-start_time").first())
        self.assertEqual(counter.membership_discount, Decimal("0"))


class AdminMembershipTests(MembershipBase):
    def test_plan_crud_admin_only(self):
        admin = client_for(make_admin())
        r = admin.post("/api/admin/membership-plans/", {
            "name": "Heritage Card Senior", "price": "799", "discount_percent": 40, "max_visitors_per_booking": 1,
            "place_slugs": [self.museum.slug],
        }, format="json")
        self.assertEqual(r.status_code, 201, r.data)
        self.assertEqual(r.data["slug"], "heritage-card-senior")
        self.assertEqual([p["slug"] for p in r.data["places"]], [self.museum.slug])
        pk = r.data["id"]
        r = admin.patch(f"/api/admin/membership-plans/{pk}/", {"discount_percent": 101}, format="json")
        self.assertEqual(r.status_code, 400)
        r = admin.patch(f"/api/admin/membership-plans/{pk}/", {"place_slugs": []}, format="json")
        self.assertTrue(r.data["all_places"])
        make_member(self.visitor, self.plan)
        self.assertEqual(admin.delete(f"/api/admin/membership-plans/{self.plan.id}/").status_code, 400)
        self.assertEqual(admin.delete(f"/api/admin/membership-plans/{pk}/").status_code, 204)
        staff = client_for(make_staff(self.museum))
        self.assertEqual(staff.get("/api/admin/membership-plans/").status_code, 403)
        self.assertEqual(staff.get("/api/admin/memberships/").status_code, 403)

    def test_search_and_cancel_with_refund(self):
        card = make_member(self.visitor, self.plan)
        make_member(make_visitor(), self.plan)
        admin = client_for(make_admin())
        r = admin.get("/api/admin/memberships/", {"search": self.visitor.email})
        self.assertEqual([m["card_number"] for m in r.data["results"]], [card.card_number])
        r = admin.get("/api/admin/memberships/", {"search": card.card_number[-4:]})
        self.assertIn(card.card_number, [m["card_number"] for m in r.data["results"]])
        r = admin.post(f"/api/admin/memberships/{card.card_number}/cancel/", {"refund": True}, format="json")
        self.assertEqual(r.status_code, 200, r.data)
        self.assertEqual((r.data["status"], r.data["refund_status"]), ("cancelled", "processed"))
        self.assertEqual(Decimal(r.data["refund_amount"]), Decimal("1499"))
        self.assertTrue(re.match(r"^MOCKRF-", Membership.objects.get(pk=card.pk).refund_id))
        self.assertEqual(admin.post(f"/api/admin/memberships/{card.card_number}/cancel/").status_code, 400)
