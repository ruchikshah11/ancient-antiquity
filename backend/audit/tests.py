from django.test import modify_settings

from audit.models import AuditEntry
from audit.services import sanitize
from bookings.tests.factories import APITestCase, client_for, make_admin, make_staff, make_visitor

WITH_AUDIT = modify_settings(MIDDLEWARE={"append": "audit.middleware.AuditMiddleware"})


class SanitizeTests(APITestCase):
    def test_secrets_are_masked(self):
        data = sanitize({
            "name": "Red Fort", "password": "x", "new_password": "y", "otp_code": "123456",
            "razorpay_signature": "s", "accessToken": "t", "credential": "c", "client_secret": "z",
            "nested": [{"refresh": "r", "note": "ok"}],
        })
        self.assertEqual(data["name"], "Red Fort")
        for key in ("password", "new_password", "otp_code", "razorpay_signature", "accessToken", "credential", "client_secret"):
            self.assertEqual(data[key], "***", key)
        self.assertEqual(data["nested"], [{"refresh": "***", "note": "ok"}])


@WITH_AUDIT
class AuditMiddlewareTests(APITestCase):
    def test_panel_user_writes_are_recorded_without_secrets(self):
        admin, visitor = make_admin(), make_visitor()
        r = client_for(admin).patch(f"/api/auth/users/{visitor.id}/", {"role": "staff"}, format="json")
        self.assertEqual(r.status_code, 200)
        entry = AuditEntry.objects.get()
        self.assertEqual((entry.user, entry.action, entry.method, entry.status_code), (admin, "update", "PATCH", 200))
        self.assertEqual(entry.changes, {"role": "staff"})
        self.assertEqual(entry.object_repr, f"email: {visitor.email}")

        staff = make_staff()
        client_for(staff).post(
            "/api/auth/change-password/", {"old_password": "secret-1", "new_password": "secret-2"}, format="json"
        )
        entry = AuditEntry.objects.get(user=staff)
        self.assertEqual(entry.changes, {"old_password": "***", "new_password": "***"})

    def test_visitors_and_reads_are_not_recorded(self):
        visitor = make_visitor()
        client_for(visitor).patch("/api/auth/me/", {"first_name": "Asha"}, format="json")
        client_for(make_admin()).get("/api/auth/users/")
        self.assertFalse(AuditEntry.objects.exists())

    def test_sign_in_endpoints_are_excluded(self):
        client_for(make_admin()).post("/api/auth/refresh/", {"refresh": "x"}, format="json")
        self.assertFalse(AuditEntry.objects.exists())


class AuditApiTests(APITestCase):
    url = "/api/admin/audit/"

    def setUp(self):
        super().setUp()
        self.admin = make_admin(email="boss@example.com")
        AuditEntry.objects.create(user=self.admin, action="update", method="PATCH",
                                  path="/api/museums/red-fort/", object_repr="name: Red Fort")
        AuditEntry.objects.create(user=None, action="login_failed", path="/api/auth/login/", object_repr="who@example.com")

    def test_admin_only(self):
        self.assertEqual(client_for(make_staff()).get(self.url).status_code, 403)
        self.assertEqual(client_for().get(self.url).status_code, 401)

    def test_filters(self):
        c = client_for(self.admin)
        self.assertEqual(c.get(self.url).data["count"], 2)
        self.assertEqual(c.get(self.url, {"action": "login_failed"}).data["count"], 1)
        self.assertEqual(c.get(self.url, {"user": self.admin.id}).data["count"], 1)
        self.assertEqual(c.get(self.url, {"user": "boss@"}).data["count"], 1)
        self.assertEqual(c.get(self.url, {"search": "red fort"}).data["count"], 1)
        self.assertEqual(c.get(self.url, {"from": "2000-01-01", "to": "2000-01-02"}).data["count"], 0)
        row = c.get(self.url, {"action": "update"}).data["results"][0]
        self.assertEqual(row["user_email"], "boss@example.com")
