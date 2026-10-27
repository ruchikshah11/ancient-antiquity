"""Web push subscriptions, WhatsApp messages and the send_visit_reminders command."""
import datetime
import io
import json
from unittest import mock

from django.core import mail
from django.core.management import call_command
from django.test import override_settings
from django.utils import timezone

from bookings.tests.factories import APITestCase, book, client_for, make_museum, make_visitor
from notifications import services
from notifications.models import NotificationLog, PushSubscription

# A real key pair (generated with `manage.py generate_vapid_keys`) so pywebpush can sign for real.
VAPID = dict(
    VAPID_PUBLIC_KEY="BKgeYMElkc1qAhPjRfsKF4mmv9ub6dvzXnt5CMnHZBDnDTytYGl_W-pHB3ojyQMHGRhhqhSlcc7T3F9vdXGMPUg",
    VAPID_PRIVATE_KEY="vusYVomOXMfnyx_LccwWECJX2zZAhpHd_iTve_t7xe8",
    VAPID_SUBJECT="mailto:test@example.com",
)
# Browser-generated subscription keys (p256dh = uncompressed P-256 point, auth = 16 bytes), from the RFC 8291 example.
SUB = {
    "endpoint": "https://fcm.googleapis.com/fcm/send/abc123",
    "keys": {
        "p256dh": "BCVxsr7N_eNgVRqvHtD0zTZsEc6-VV-JvLexhqUzORcxaOzi6-AYWXvTBHm4bjyPjs7Vd8pZGH6SRpkNtoIAiw4",
        "auth": "BTBZMqHH6r4Tts7J_aSIgg",
    },
}


class FakeResponse:
    def __init__(self, status_code):
        self.status_code = status_code
        self.text = ""
        self.reason = "Gone" if status_code == 410 else "Created"
        self.content = b""
        self.headers = {}


@override_settings(**VAPID)
class PushSubscriptionApiTests(APITestCase):
    def setUp(self):
        super().setUp()
        self.visitor = make_visitor()
        self.client = client_for(self.visitor)

    def test_public_key(self):
        r = client_for().get("/api/notifications/push/public-key/")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.data["public_key"], VAPID["VAPID_PUBLIC_KEY"])
        with override_settings(VAPID_PRIVATE_KEY=""):
            self.assertIsNone(client_for().get("/api/notifications/push/public-key/").data["public_key"])

    def test_subscribe_and_unsubscribe(self):
        self.assertEqual(client_for().post("/api/notifications/push/subscribe/", SUB, format="json").status_code, 401)
        r = self.client.post("/api/notifications/push/subscribe/", SUB, format="json")
        self.assertEqual(r.status_code, 201, r.data)
        r = self.client.post("/api/notifications/push/subscribe/", SUB, format="json")  # idempotent
        self.assertEqual(r.status_code, 200)
        self.assertEqual(PushSubscription.objects.filter(user=self.visitor).count(), 1)
        r = self.client.post("/api/notifications/push/unsubscribe/", {"endpoint": SUB["endpoint"]}, format="json")
        self.assertEqual(r.data["removed"], 1)
        self.assertFalse(PushSubscription.objects.exists())

    def test_rejects_bad_subscription(self):
        bad = {"endpoint": "http://insecure.example.com/x", "keys": SUB["keys"]}
        self.assertEqual(self.client.post("/api/notifications/push/subscribe/", bad, format="json").status_code, 400)
        no_keys = {"endpoint": SUB["endpoint"]}
        self.assertEqual(self.client.post("/api/notifications/push/subscribe/", no_keys, format="json").status_code, 400)

    def test_subscribe_refused_when_not_configured(self):
        with override_settings(VAPID_PUBLIC_KEY=""):
            r = self.client.post("/api/notifications/push/subscribe/", SUB, format="json")
        self.assertEqual(r.status_code, 400)


@override_settings(**VAPID, SMS_PROVIDER="console", WHATSAPP_PROVIDER="console",
                   RAZORPAY_KEY_ID="", RAZORPAY_KEY_SECRET="")
class ReminderTests(APITestCase):
    def setUp(self):
        super().setUp()
        self.museum = make_museum("Indian Museum")
        self.visitor = make_visitor()
        self.tomorrow = timezone.localdate() + datetime.timedelta(days=1)

    def _subscribe(self):
        return PushSubscription.objects.create(
            user=self.visitor, endpoint=SUB["endpoint"], p256dh=SUB["keys"]["p256dh"], auth=SUB["keys"]["auth"])

    def test_day_before_reminder_all_channels_once(self):
        booking = book(self.visitor, self.museum, visit_date=self.tomorrow, confirm=True)
        book(self.visitor, self.museum, visit_date=self.tomorrow)  # pending: no reminder
        later = book(self.visitor, self.museum, visit_date=self.tomorrow + datetime.timedelta(days=3), confirm=True)
        self._subscribe()
        mail.outbox.clear()
        with mock.patch("pywebpush.requests.post", return_value=FakeResponse(201)) as post:
            out = io.StringIO()
            call_command("send_visit_reminders", stdout=out)
            call_command("send_visit_reminders", stdout=io.StringIO())  # second run sends nothing
        self.assertIn("sent 1", out.getvalue())
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn("Reminder", mail.outbox[0].subject)
        self.assertIn("TOMORROW", mail.outbox[0].body)
        channels = set(NotificationLog.objects.filter(booking=booking, kind="reminder").values_list("channel", flat=True))
        self.assertEqual(channels, {"email", "sms", "whatsapp", "push"})
        self.assertEqual(post.call_count, 1)
        self.assertEqual(post.call_args.args[0], SUB["endpoint"])
        self.assertIn("Authorization", post.call_args.kwargs["headers"])  # VAPID-signed
        self.assertFalse(NotificationLog.objects.filter(booking=later, kind="reminder").exists())

    def test_gone_subscription_is_deleted(self):
        book(self.visitor, self.museum, visit_date=self.tomorrow, confirm=True)
        self._subscribe()
        with mock.patch("pywebpush.requests.post", return_value=FakeResponse(410)):
            call_command("send_visit_reminders", stdout=io.StringIO())
        self.assertFalse(PushSubscription.objects.exists())
        self.assertEqual(NotificationLog.objects.get(channel="push").status, NotificationLog.Status.FAILED)

    def test_hours_before(self):
        now = timezone.localtime()
        slot = self.museum.slots.create(
            start_time=(now + datetime.timedelta(minutes=90)).time().replace(second=0, microsecond=0),
            end_time=datetime.time(23, 59, 59), capacity=50,
        ) if (now + datetime.timedelta(minutes=90)).date() == now.date() else None
        if slot is None:
            self.skipTest("too close to midnight")
        booking = book(self.visitor, self.museum, slot=slot, visit_date=now.date(), confirm=True)
        call_command("send_visit_reminders", "--hours-before", "2", stdout=io.StringIO())
        self.assertTrue(NotificationLog.objects.filter(booking=booking, kind="reminder_soon", channel="email").exists())
        self.assertFalse(NotificationLog.objects.filter(booking=booking, kind="reminder").exists())

    def test_dry_run_sends_nothing(self):
        book(self.visitor, self.museum, visit_date=self.tomorrow, confirm=True)
        mail.outbox.clear()
        out = io.StringIO()
        call_command("send_visit_reminders", "--dry-run", stdout=out)
        self.assertIn("would remind", out.getvalue())
        self.assertEqual(len(mail.outbox), 0)
        self.assertFalse(NotificationLog.objects.filter(kind="reminder").exists())


class WhatsAppTests(APITestCase):
    def setUp(self):
        super().setUp()
        self.museum = make_museum()
        self.visitor = make_visitor()

    @override_settings(WHATSAPP_PROVIDER="meta", WHATSAPP_TOKEN="tok", WHATSAPP_PHONE_NUMBER_ID="12345",
                       SMS_PROVIDER="console")
    def test_meta_cloud_api_on_confirmation(self):
        booking = book(self.visitor, self.museum)
        with mock.patch("notifications.services._post", return_value="{}") as post:
            with self.captureOnCommitCallbacks(execute=True):
                from bookings import services as booking_services
                booking_services.confirm_payment(booking, "upi")
        url, payload, headers = post.call_args.args
        self.assertEqual(url, "https://graph.facebook.com/v20.0/12345/messages")
        body = json.loads(payload)
        self.assertEqual(body["to"], "919876543210")
        self.assertIn(f"/tickets/{booking.reference}", body["text"]["body"])
        self.assertEqual(headers["Authorization"], "Bearer tok")
        log = NotificationLog.objects.get(channel="whatsapp", kind="confirmed")
        self.assertEqual(log.status, NotificationLog.Status.SENT)

    @override_settings(WHATSAPP_PROVIDER="off")
    def test_disabled(self):
        self.assertFalse(services.whatsapp_enabled())

    @override_settings(WHATSAPP_PROVIDER="meta", WHATSAPP_TOKEN="", WHATSAPP_PHONE_NUMBER_ID="")
    def test_meta_without_keys_is_skipped(self):
        log = services.send_whatsapp("9876543210", "hi", kind="test")
        self.assertEqual(log.status, NotificationLog.Status.SKIPPED)
