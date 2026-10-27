"""Pricing suggestions: the fill-rate maths, closures, the revenue estimate and staff scoping."""
import datetime
from decimal import Decimal

from accounts.models import User
from bookings.models import Booking
from bookings.tests.factories import (
    APITestCase, client_for, make_admin, make_museum, make_staff, make_user, make_visitor,
)
from museums.models import PlaceClosure, PriceRule

from . import services

TODAY = datetime.date(2026, 6, 1)  # a Monday; the 4-week window is 4 May .. 31 May 2026


def window(weeks=4):
    start = TODAY - datetime.timedelta(days=7 * weeks)
    return [start + datetime.timedelta(days=i) for i in range(7 * weeks)]


class MathTests(APITestCase):
    def test_percent_scales(self):
        self.assertEqual(services.premium_percent(0.85), 10)
        self.assertEqual(services.premium_percent(0.925), 15)
        self.assertEqual(services.premium_percent(1.0), 20)
        self.assertEqual(services.premium_percent(1.4), 20)  # overbooked days don't push past +20 %
        self.assertEqual(services.discount_percent(0.25), 10)
        self.assertEqual(services.discount_percent(0.125), round(17.5))
        self.assertEqual(services.discount_percent(0.0), 25)

    def test_classify_needs_consistency_and_data(self):
        self.assertEqual(services.classify([0.9, 0.95]), ("nodata", 0))  # fewer than 3 days
        self.assertEqual(services.classify([0.9, 0.9, 0.9, 0.9]), ("busy", 13))
        # Average over 85 % thanks to one packed day, but most days were not busy: not "consistently" busy.
        self.assertEqual(services.classify([2.0, 0.6, 0.6, 0.6])[0], "normal")
        self.assertEqual(services.classify([0.1, 0.1, 0.1, 0.1]), ("quiet", -19))
        self.assertEqual(services.classify([0.5, 0.5, 0.5])[0], "normal")

    def test_estimate_caps_at_capacity(self):
        v0, v1, r0, r1 = services.estimate(90, 50.0, 100, -20, 0.5)
        self.assertEqual(v0, 90)
        self.assertAlmostEqual(v1, 99)
        v0, v1, r0, r1 = services.estimate(90, 50.0, 95, -20, 0.5)
        self.assertEqual(v1, 95)  # +10 % would be 99 but the slot holds 95
        self.assertAlmostEqual(r1, 95 * 50 * 0.8)


class SuggestionTests(APITestCase):
    def setUp(self):
        super().setUp()
        self.museum = make_museum(slots=(
            (datetime.time(10, 0), datetime.time(11, 0), 100), (datetime.time(14, 0), datetime.time(15, 0), 100),
        ))
        self.morning, self.afternoon = list(self.museum.slots.order_by("start_time"))
        self.visitor = make_visitor()
        rows = []

        def add(day, slot, visitors, status=Booking.Status.CONFIRMED):
            rows.append(Booking(
                user=self.visitor, museum=self.museum, slot=slot, visit_date=day, status=status,
                total_visitors=visitors, total_amount=Decimal(visitors * 50), visitor_name="Asha",
            ))

        saturdays = [d for d in window() if d.weekday() == 5]
        mondays = [d for d in window() if d.weekday() == 0]
        for day in saturdays[1:]:  # the first Saturday is closed all day (no bookings)
            add(day, self.morning, 95)
            add(day, self.afternoon, 50)
            add(day, self.afternoon, 30, status=Booking.Status.CANCELLED)  # cancelled: never counted
        PlaceClosure.objects.create(museum=self.museum, start_date=saturdays[0], end_date=saturdays[0], reason="Repairs")
        for day in mondays:
            add(day, self.morning, 50)
            add(day, self.afternoon, 10)
        # One Monday afternoon was closed (partial closure): its stray booking must not count.
        partial = PlaceClosure.objects.create(
            museum=self.museum, start_date=mondays[0], end_date=mondays[0], reason="VIP visit", all_day=False,
        )
        partial.slots.add(self.afternoon)
        add(mondays[0], self.afternoon, 100)
        Booking.objects.bulk_create(rows)

    def run_suggestions(self, **kw):
        return services.pricing_suggestions(self.museum, TODAY, weeks=4, **kw)

    def cell(self, data, weekday, slot):
        row = next(r for r in data["grid"] if r["weekday"] == weekday)
        return next(c for c in row["cells"] if c["slot"] == slot.id)

    def test_grid_excludes_closed_days_and_slots(self):
        data = self.run_suggestions()
        sat_morning = self.cell(data, 5, self.morning)
        self.assertEqual(sat_morning["days"], 3)  # 4 Saturdays minus the closed one
        self.assertEqual(sat_morning["fill"], 0.95)
        self.assertEqual(sat_morning["status"], "busy")
        self.assertEqual(sat_morning["suggested_percent"], 17)  # 10 + 10 x (0.95 - 0.85) / 0.15 = 16.7
        mon_afternoon = self.cell(data, 0, self.afternoon)
        self.assertEqual(mon_afternoon["days"], 3)  # the partially closed afternoon is left out
        self.assertEqual(mon_afternoon["fill"], 0.1)
        self.assertEqual(mon_afternoon["status"], "quiet")
        self.assertEqual(mon_afternoon["suggested_percent"], -19)  # 10 + 15 x (0.25 - 0.1) / 0.25
        tue = self.cell(data, 1, self.morning)
        self.assertEqual((tue["fill"], tue["status"]), (0.0, "quiet"))  # open but empty days count as 0 %

    def test_weekly_closed_day_is_closed(self):
        self.museum.closed_weekday = 1
        self.museum.save()
        data = self.run_suggestions()
        self.assertEqual(self.cell(data, 1, self.morning)["status"], "closed")
        self.assertNotIn(1, [s["weekday"] for s in data["suggestions"]])

    def test_premium_suggestion_and_revenue_estimate(self):
        data = self.run_suggestions(elasticity=0.5)
        sat = next(s for s in data["suggestions"] if s["weekday"] == 5)
        self.assertEqual((sat["kind"], sat["percent"], sat["all_slots"], sat["conflict"]), ("premium", 17, False, False))
        # Whole day (a rule covers every slot): 95 + 50 visitors at Rs 50 now = Rs 7,250 per Saturday.
        # +17 % with elasticity 0.5 -> visitors x 0.915 at Rs 58.50.
        expected = (95 * 0.915 + 50 * 0.915) * 58.5
        self.assertEqual(sat["revenue_per_week"]["current"], 7250.0)
        self.assertAlmostEqual(sat["revenue_per_week"]["estimated"], expected, places=1)
        self.assertAlmostEqual(sat["revenue_change_over_period"], round((expected - 7250) * 4, 2), places=1)
        self.assertEqual(sat["visitors_per_week"], {"current": 145.0, "estimated": round(145 * 0.915, 1)})
        self.assertEqual(sat["rule"]["weekdays"], "5")
        self.assertEqual(sat["rule"]["value"], "17")
        self.assertIn("-0.5", data["assumption"])

    def test_discount_suggestion(self):
        data = self.run_suggestions()
        mon = next(s for s in data["suggestions"] if s["weekday"] == 0)
        self.assertEqual((mon["kind"], mon["percent"]), ("discount", -19))
        self.assertEqual([s["slot"] for s in mon["slots"]], [self.afternoon.id])
        # Zero elasticity: same visitors, 19 % less money.
        flat = next(s for s in self.run_suggestions(elasticity=0)["suggestions"] if s["weekday"] == 0)
        self.assertAlmostEqual(flat["revenue_per_week"]["change"], -0.19 * flat["revenue_per_week"]["current"], places=1)

    def test_rule_payload_is_accepted_by_price_rule_api(self):
        sat = next(s for s in self.run_suggestions()["suggestions"] if s["weekday"] == 5)
        r = client_for(make_admin()).post("/api/admin/price-rules/", sat["rule"], format="json")
        self.assertEqual(r.status_code, 201, r.data)
        rule = PriceRule.objects.get(pk=r.data["id"])
        self.assertEqual((rule.weekday_list, rule.value), ([5], Decimal("17")))


class ScopingTests(APITestCase):
    URL = "/api/admin/pricing-suggestions/"

    def setUp(self):
        super().setUp()
        self.mine, self.other = make_museum(), make_museum()
        self.staff = make_staff(self.mine)

    def test_staff_only_their_places(self):
        c = client_for(self.staff)
        r = c.get(self.URL, {"museum": self.mine.slug, "weeks": 4})
        self.assertEqual(r.status_code, 200, r.data)
        self.assertFalse(r.data["can_create_rules"])
        self.assertEqual(c.get(self.URL, {"museum": self.other.slug}).status_code, 403)
        self.assertEqual(c.get(self.URL, {"museum": "nope"}).status_code, 404)
        self.assertEqual(c.get(self.URL).status_code, 400)

    def test_admin_any_place(self):
        r = client_for(make_admin()).get(self.URL, {"museum": self.other.slug})
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.data["can_create_rules"])
        self.assertEqual(r.data["weeks"], 12)

    def test_non_panel_users_refused(self):
        for user in (make_visitor(), make_user(User.Role.PARTNER), make_user(User.Role.AGENT)):
            self.assertEqual(client_for(user).get(self.URL, {"museum": self.mine.slug}).status_code, 403)
        self.assertEqual(client_for().get(self.URL, {"museum": self.mine.slug}).status_code, 401)
