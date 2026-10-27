from django.core.cache import cache
from django.test import TestCase
from rest_framework.test import APIClient

from accounts.models import User

from .models import ContactMessage


class ContactTests(TestCase):
    def setUp(self):
        cache.clear()
        self.client = APIClient()
        self.payload = {
            "name": "Asha Rao",
            "email": "asha@example.com",
            "topic": "data",
            "place_slug": "red-fort",
            "message": "The opening hours on this page are out of date.",
        }

    def test_info_is_public(self):
        r = self.client.get("/api/support/info/")
        self.assertEqual(r.status_code, 200)
        self.assertIn("email", r.data)

    def test_create_message(self):
        r = self.client.post("/api/support/contact/", self.payload, format="json")
        self.assertEqual(r.status_code, 201, r.data)
        msg = ContactMessage.objects.get()
        self.assertEqual(msg.status, "new")
        self.assertEqual(msg.place_slug, "red-fort")

    def test_honeypot_stores_nothing(self):
        r = self.client.post("/api/support/contact/", {**self.payload, "website": "spam"}, format="json")
        self.assertEqual(r.status_code, 201)
        self.assertFalse(ContactMessage.objects.exists())

    def test_throttled_after_five(self):
        for _ in range(5):
            self.assertEqual(self.client.post("/api/support/contact/", self.payload, format="json").status_code, 201)
        self.assertEqual(self.client.post("/api/support/contact/", self.payload, format="json").status_code, 429)

    def test_admin_list_and_patch(self):
        msg = ContactMessage.objects.create(name="A", email="a@example.com", message="Hello there, please help")
        self.assertEqual(self.client.get("/api/admin/support-messages/").status_code, 401)
        staff = User.objects.create_user(email="staff@example.com", password="x-Strong-pass-1", role=User.Role.STAFF)
        self.client.force_authenticate(staff)
        r = self.client.get("/api/admin/support-messages/")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.data["count"], 1)
        r = self.client.patch(f"/api/admin/support-messages/{msg.id}/", {"status": "closed", "message": "x"}, format="json")
        self.assertEqual(r.status_code, 200)
        msg.refresh_from_db()
        self.assertEqual(msg.status, "closed")
        self.assertEqual(msg.message, "Hello there, please help")  # read-only
