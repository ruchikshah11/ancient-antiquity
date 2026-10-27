from unittest import mock

from django.core import mail
from django.core.mail import send_mail
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import override_settings

from accounts.models import User
from bookings.models import Booking
from bookings.tests.factories import APITestCase, book, make_museum, make_user, make_visitor
from demo.management.commands.seed_demo_data import KEEP_EMAILS
from museums.models import Museum, Review


class SeedDemoDataTests(APITestCase):
    def setUp(self):
        super().setUp()
        for email, role in zip(KEEP_EMAILS, (User.Role.ADMIN, User.Role.STAFF, User.Role.VISITOR)):
            make_user(role, email=email, first_name="Demo")
        self.places = [
            make_museum(f"Place {i}", is_featured=True, tickets=(("Indian adult", "50.00"), ("Child", "0.00"), ("Foreign national", "600.00")))
            for i in range(4)
        ]
        Museum.objects.filter(pk=self.places[0].pk).update(place_type=Museum.PlaceType.FORT)
        self.old = make_visitor(email="tester@example.org")
        book(self.old, self.places[0], confirm=True)

    def run_seed(self, *args):
        # Never touch the real docs/LOGIN_DETAILS.md from a test.
        with mock.patch("demo.management.commands.seed_demo_data.Command.write_login_details"):
            call_command("seed_demo_data", *args, stdout=mock.MagicMock())

    def test_requires_explicit_wipe(self):
        with self.assertRaises(CommandError):
            self.run_seed("--yes")
        self.assertTrue(User.objects.filter(email="tester@example.org").exists())

    def test_replaces_activity_and_keeps_demo_logins(self):
        self.run_seed("--wipe", "--yes", "--users", "40")
        self.assertFalse(User.objects.filter(email="tester@example.org").exists())
        self.assertEqual(set(User.objects.filter(email__in=KEEP_EMAILS).values_list("email", flat=True)), set(KEEP_EMAILS))
        self.assertEqual(User.objects.count(), len(KEEP_EMAILS) + 15 + 40)  # 12 visitors, staff, tour operator, kiosk + bulk
        seeded = User.objects.exclude(email__in=KEEP_EMAILS)
        self.assertFalse(seeded.filter(is_sample=False).exists())  # every seeded account is guarded
        self.assertFalse(seeded.filter(email__endswith="@example.com").exists())
        self.assertEqual(seeded.values("email").distinct().count(), seeded.count())
        self.assertTrue(Museum.objects.count() == 4)  # places are configuration, never wiped
        online = Booking.objects.filter(channel=Booking.Channel.ONLINE)
        self.assertGreater(online.count(), 30)
        self.assertTrue(online.filter(status=Booking.Status.CHECKED_IN).exists())
        self.assertTrue(online.filter(visit_date__gt=Booking.objects.order_by("visit_date").first().visit_date).exists())
        self.assertGreater(Review.objects.count(), 0)
        for b in online.filter(status=Booking.Status.CONFIRMED)[:20]:
            self.assertGreater(b.total_visitors, 0)
            self.assertIsNotNone(b.paid_at)

    def test_mass_mode_writes_priced_bookings_fast(self):
        from bookings.models import BookingItem, GateScan

        self.run_seed("--wipe", "--yes", "--users", "0", "--mass-users", "200")
        mass = User.objects.filter(is_sample=True).exclude(email__in=KEEP_EMAILS)
        self.assertGreaterEqual(mass.count(), 200)
        bookings = Booking.objects.filter(user__in=mass)
        self.assertGreater(bookings.count(), 60)
        for b in bookings.prefetch_related("items")[:40]:
            # Totals match the ticket lines, like a booking made through the service.
            self.assertEqual(b.total_amount, sum(i.unit_price * i.quantity for i in b.items.all()))
            self.assertEqual(b.total_visitors, sum(i.quantity for i in b.items.all()))
            self.assertLessEqual(b.created_at, b.paid_at)
        checked = bookings.filter(status=Booking.Status.CHECKED_IN)
        self.assertEqual(GateScan.objects.filter(booking__in=checked).count(), checked.count())
        self.assertTrue(BookingItem.objects.filter(booking__in=bookings).exists())
    def test_append_adds_without_deleting(self):
        self.run_seed("--wipe", "--yes", "--users", "30")
        users, bookings = User.objects.count(), Booking.objects.count()
        first_booking = Booking.objects.order_by("id").first().reference
        with mock.patch("demo.management.commands.seed_demo_data.Command.append_csv"):
            call_command("seed_demo_data", "--append", "--users", "0", "--mass-users", "20", "--mass-bookings", "500",
                         stdout=mock.MagicMock())
        self.assertEqual(User.objects.count(), users + 20)  # only additions
        self.assertGreater(Booking.objects.count(), bookings + 300)
        self.assertTrue(Booking.objects.filter(reference=first_booking).exists())  # earlier data untouched
        self.assertTrue(User.objects.filter(email__in=KEEP_EMAILS).count() == 3)

    def test_wipe_and_append_are_exclusive(self):
        with self.assertRaises(CommandError):
            self.run_seed("--wipe", "--append", "--yes")

@override_settings(EMAIL_BACKEND="notifications.mail.SampleSafeEmailBackend",
                   REAL_EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend", SMS_PROVIDER="console")
class SampleGuardTests(APITestCase):
    """Seeded addresses may belong to real people: they must never get email or SMS, whatever the providers."""

    def test_email_to_sample_accounts_is_dropped(self):
        make_visitor(email="priya.sharma@gmail.com", is_sample=True)
        make_visitor(email="real.person@gmail.com")
        mail.outbox = []
        send_mail("Hi", "x", None, ["Priya <priya.sharma@gmail.com>"])  # only a sample recipient: nothing sent
        send_mail("Hi", "x", None, ["priya.sharma@gmail.com", "real.person@gmail.com"])
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].to, ["real.person@gmail.com"])

    def test_sms_to_sample_accounts_is_skipped(self):
        from notifications.models import NotificationLog
        from notifications.services import send_sms

        make_visitor(email="kabir@yahoo.co.in", phone="9876501234", is_sample=True)
        log = send_sms("+91 98765 01234", "hello")
        self.assertEqual((log.status, log.error), (NotificationLog.Status.SKIPPED, "Sample-data account"))
        self.assertEqual(send_sms("9123456789", "hello").status, NotificationLog.Status.SENT)
