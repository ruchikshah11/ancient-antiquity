import re
import unittest
from unittest import mock

import pyotp
from django.contrib.auth.tokens import default_token_generator
from django.core import mail
from django.test import override_settings
from django.utils.encoding import force_bytes
from django.utils.http import urlsafe_base64_encode

from accounts.models import LoginOTP, User
from audit.models import AuditEntry
from bookings.tests.factories import APITestCase, client_for, make_admin, make_staff, make_visitor

STRONG = "Heritage-Walk-2026!"


class RegisterTests(APITestCase):
    url = "/api/auth/register/"

    def test_register_returns_tokens_and_stores_argon2_hash(self):
        r = client_for().post(self.url, {"email": "asha@example.com", "password": STRONG, "first_name": "Asha"})
        self.assertEqual(r.status_code, 201, r.data)
        self.assertIn("access", r.data)
        self.assertIn("refresh", r.data)
        self.assertEqual(r.data["user"]["email"], "asha@example.com")
        self.assertEqual(r.data["user"]["role"], "visitor")
        user = User.objects.get(email="asha@example.com")
        self.assertTrue(user.password.startswith("argon2"), "passwords must be hashed with Argon2")
        self.assertNotIn(STRONG, user.password)
        self.assertTrue(user.check_password(STRONG))

    def test_duplicate_email_rejected(self):
        make_visitor(email="asha@example.com")
        r = client_for().post(self.url, {"email": "asha@example.com", "password": STRONG})
        self.assertEqual(r.status_code, 400)
        self.assertIn("email", r.data)

    # BUG: emails are only lower-cased in the domain part (BaseUserManager.normalize_email), and the unique
    # constraint is case-sensitive, so "Asha@example.com" can register next to "asha@example.com". Login is
    # case-sensitive too, while password reset matches email__iexact and picks .first() - it can email the
    # reset link for the wrong one of the two accounts.
    def test_duplicate_email_with_different_case_rejected(self):
        make_visitor(email="asha@example.com")
        r = client_for().post(self.url, {"email": "Asha@example.com", "password": STRONG})
        self.assertEqual(r.status_code, 400)

    def test_weak_password_rejected(self):
        r = client_for().post(self.url, {"email": "weak@example.com", "password": "12345678"})
        self.assertEqual(r.status_code, 400)
        self.assertIn("password", r.data)
        self.assertFalse(User.objects.filter(email="weak@example.com").exists())

    def test_role_cannot_be_chosen_at_signup(self):
        r = client_for().post(self.url, {"email": "sneaky@example.com", "password": STRONG, "role": "admin"})
        self.assertEqual(r.status_code, 201)
        self.assertEqual(User.objects.get(email="sneaky@example.com").role, User.Role.VISITOR)


class LoginTests(APITestCase):
    def setUp(self):
        super().setUp()
        self.user = make_visitor(email="ravi@example.com", password=STRONG, first_name="Ravi")

    def test_login_returns_user_and_tokens(self):
        r = client_for().post("/api/auth/login/", {"email": "ravi@example.com", "password": STRONG})
        self.assertEqual(r.status_code, 200, r.data)
        self.assertIn("access", r.data)
        self.assertIn("refresh", r.data)
        self.assertEqual(r.data["user"]["email"], "ravi@example.com")
        self.assertFalse(r.data["user"]["is_panel_user"])

        me = client_for()
        me.credentials(HTTP_AUTHORIZATION=f"Bearer {r.data['access']}")
        r = me.get("/api/auth/me/")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.data["first_name"], "Ravi")

    def test_wrong_password_rejected(self):
        r = client_for().post("/api/auth/login/", {"email": "ravi@example.com", "password": "nope-nope-nope"})
        self.assertEqual(r.status_code, 401)

    def test_me_requires_authentication(self):
        self.assertEqual(client_for().get("/api/auth/me/").status_code, 401)

    def test_role_flags(self):
        staff, admin = make_staff(), make_admin()
        self.assertTrue(staff.is_panel_user)
        self.assertFalse(staff.is_admin_role)
        self.assertTrue(admin.is_panel_user and admin.is_admin_role)
        self.assertFalse(self.user.is_panel_user)

    def test_user_admin_is_admin_only(self):
        self.assertEqual(client_for(self.user).get("/api/auth/users/").status_code, 403)
        self.assertEqual(client_for(make_staff()).get("/api/auth/users/").status_code, 403)
        self.assertEqual(client_for(make_admin()).get("/api/auth/users/").status_code, 200)


class PasswordResetTests(APITestCase):
    request_url = "/api/auth/password-reset/"
    confirm_url = "/api/auth/password-reset/confirm/"

    def setUp(self):
        super().setUp()
        self.user = make_visitor(email="meera@example.com", password=STRONG)

    def _link_parts(self):
        return urlsafe_base64_encode(force_bytes(self.user.pk)), default_token_generator.make_token(self.user)

    def test_request_for_real_user_sends_email(self):
        r = client_for().post(self.request_url, {"email": "MEERA@example.com"})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].to, ["meera@example.com"])
        uid, _ = self._link_parts()
        self.assertIn(f"/reset-password/{uid}/", mail.outbox[0].body)

    def test_request_for_unknown_email_gives_same_answer_and_sends_nothing(self):
        known = client_for().post(self.request_url, {"email": "meera@example.com"})
        mail.outbox.clear()
        unknown = client_for().post(self.request_url, {"email": "nobody@example.com"})
        self.assertEqual(unknown.status_code, 200)
        self.assertEqual(known.data, unknown.data)
        self.assertEqual(len(mail.outbox), 0)

    def test_confirm_with_valid_token_changes_password_and_token_dies(self):
        uid, token = self._link_parts()
        new = "Another-Strong-Pass-99"
        r = client_for().post(self.confirm_url, {"uid": uid, "token": token, "new_password": new})
        self.assertEqual(r.status_code, 200, r.data)
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password(new))

        reused = client_for().post(self.confirm_url, {"uid": uid, "token": token, "new_password": "Yet-Another-Pass-77"})
        self.assertEqual(reused.status_code, 400)
        self.assertIn("token", reused.data)

    def test_confirm_with_invalid_token_or_uid(self):
        uid, _ = self._link_parts()
        r = client_for().post(self.confirm_url, {"uid": uid, "token": "bad-token", "new_password": "Another-Strong-Pass-99"})
        self.assertEqual(r.status_code, 400)
        self.assertIn("token", r.data)
        r = client_for().post(self.confirm_url, {"uid": "garbage", "token": "x", "new_password": "Another-Strong-Pass-99"})
        self.assertEqual(r.status_code, 400)
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password(STRONG))

    def test_confirm_rejects_weak_new_password(self):
        uid, token = self._link_parts()
        r = client_for().post(self.confirm_url, {"uid": uid, "token": token, "new_password": "password"})
        self.assertEqual(r.status_code, 400)
        self.assertIn("new_password", r.data)


# ------------------------------------------------------------------ Google / one-time codes / two-step verification

GOOGLE_ID = "test-client.apps.googleusercontent.com"
VERIFY = "google.oauth2.id_token.verify_oauth2_token"


def google_claims(**kw):
    claims = {"sub": "1234567890", "email": "kavya@example.com", "email_verified": True,
              "given_name": "Kavya", "family_name": "Rao"}
    claims.update(kw)
    return claims


def other_code(code):
    return "000000" if code != "000000" else "111111"


class LoginMethodsTests(APITestCase):
    @override_settings(GOOGLE_CLIENT_ID=GOOGLE_ID, OTP_LOGIN_ENABLED=True, SMS_PROVIDER="console", DEBUG=True)
    def test_methods_lists_enabled_options(self):
        r = client_for().get("/api/auth/methods/")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.data, {"google_client_id": GOOGLE_ID, "otp_email": True, "otp_sms": True, "password": True})

    @override_settings(GOOGLE_CLIENT_ID="", OTP_LOGIN_ENABLED=False)
    def test_methods_when_disabled(self):
        r = client_for().get("/api/auth/methods/")
        self.assertIsNone(r.data["google_client_id"])
        self.assertFalse(r.data["otp_email"])
        self.assertFalse(r.data["otp_sms"])


@override_settings(GOOGLE_CLIENT_ID=GOOGLE_ID)
class GoogleLoginTests(APITestCase):
    url = "/api/auth/google/"

    def test_new_google_user_becomes_visitor(self):
        with mock.patch(VERIFY, return_value=google_claims()) as verify:
            r = client_for().post(self.url, {"credential": "abc"})
        self.assertEqual(r.status_code, 200, r.data)
        self.assertEqual(verify.call_args.args[0], "abc")
        self.assertEqual(verify.call_args.args[2], GOOGLE_ID)
        self.assertIn("access", r.data)
        user = User.objects.get(email="kavya@example.com")
        self.assertEqual((user.first_name, user.last_name, user.role, user.google_sub), ("Kavya", "Rao", "visitor", "1234567890"))
        self.assertFalse(user.has_usable_password())
        self.assertTrue(AuditEntry.objects.filter(user=user, action="login").exists())

    def test_existing_account_is_linked_case_insensitively(self):
        existing = make_visitor(email="kavya@example.com")
        with mock.patch(VERIFY, return_value=google_claims(email="Kavya@Example.com")):
            r = client_for().post(self.url, {"credential": "abc"})
        self.assertEqual(r.status_code, 200, r.data)
        self.assertEqual(r.data["user"]["id"], existing.id)
        existing.refresh_from_db()
        self.assertEqual(existing.google_sub, "1234567890")
        self.assertEqual(User.objects.count(), 1)

    def test_unverified_email_rejected(self):
        with mock.patch(VERIFY, return_value=google_claims(email_verified=False)):
            r = client_for().post(self.url, {"credential": "abc"})
        self.assertEqual(r.status_code, 400)
        self.assertFalse(User.objects.exists())

    def test_invalid_token_rejected(self):
        with mock.patch(VERIFY, side_effect=ValueError("Wrong audience")):
            r = client_for().post(self.url, {"credential": "abc"})
        self.assertEqual(r.status_code, 400)
        self.assertTrue(AuditEntry.objects.filter(action="login_failed").exists())

    @override_settings(GOOGLE_CLIENT_ID="")
    def test_not_configured(self):
        self.assertEqual(client_for().post(self.url, {"credential": "abc"}).status_code, 400)


@override_settings(OTP_LOGIN_ENABLED=True, OTP_TTL_MINUTES=10, SMS_PROVIDER="console", DEBUG=True)
class OTPLoginTests(APITestCase):
    request_url = "/api/auth/otp/request/"
    verify_url = "/api/auth/otp/verify/"

    def _email_code(self):
        return re.search(r"\b(\d{6})\b", mail.outbox[-1].body).group(1)

    def _logged_code(self, logs):
        return re.search(r"code for \S+: (\d{6})", "\n".join(logs.output)).group(1)

    def test_email_code_logs_in_existing_user_and_only_hash_is_stored(self):
        user = make_visitor(email="neha@example.com")
        r = client_for().post(self.request_url, {"email": "Neha@example.com"})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(mail.outbox[-1].to, ["neha@example.com"])
        code = self._email_code()
        otp = LoginOTP.objects.get()
        self.assertNotIn(code, otp.code_hash)
        r = client_for().post(self.verify_url, {"email": "neha@example.com", "code": code})
        self.assertEqual(r.status_code, 200, r.data)
        self.assertEqual(r.data["user"]["id"], user.id)
        r = client_for().post(self.verify_url, {"email": "neha@example.com", "code": code})
        self.assertEqual(r.status_code, 400, "codes are single use")

    def test_email_code_creates_visitor_when_no_account(self):
        client_for().post(self.request_url, {"email": "new@example.com"})
        r = client_for().post(self.verify_url, {"email": "new@example.com", "code": self._email_code()})
        self.assertEqual(r.status_code, 200, r.data)
        self.assertTrue(r.data.get("created"))
        self.assertEqual(User.objects.get(email="new@example.com").role, "visitor")

    def test_wrong_code_counts_attempts_and_locks_after_five(self):
        client_for().post(self.request_url, {"email": "lock@example.com"})
        code = self._email_code()
        for _ in range(5):
            r = client_for().post(self.verify_url, {"email": "lock@example.com", "code": other_code(code)})
            self.assertEqual(r.status_code, 400)
        r = client_for().post(self.verify_url, {"email": "lock@example.com", "code": code})
        self.assertEqual(r.status_code, 400)
        self.assertFalse(User.objects.filter(email="lock@example.com").exists())

    def test_expired_code_rejected(self):
        client_for().post(self.request_url, {"email": "late@example.com"})
        code = self._email_code()
        LoginOTP.objects.update(expires_at=LoginOTP.objects.get().created_at)
        self.assertEqual(client_for().post(self.verify_url, {"email": "late@example.com", "code": code}).status_code, 400)

    def test_per_destination_limit_is_silent(self):
        for _ in range(4):
            self.assertEqual(client_for().post(self.request_url, {"email": "spam@example.com"}).status_code, 200)
        self.assertEqual(len(mail.outbox), 3)

    def test_per_ip_throttle(self):
        statuses = [client_for().post(self.request_url, {"email": f"ip{i}@example.com"}).status_code for i in range(6)]
        self.assertEqual(statuses, [200] * 5 + [429])

    def test_sms_code_logs_in_user_with_that_phone(self):
        user = make_visitor(phone="+91 98765 43210")
        with self.assertLogs("accounts.auth_services", level="WARNING") as logs:
            r = client_for().post(self.request_url, {"phone": "9876543210"})
        self.assertEqual(r.status_code, 200)
        r = client_for().post(self.verify_url, {"phone": "09876543210", "code": self._logged_code(logs)})
        self.assertEqual(r.status_code, 200, r.data)
        self.assertEqual(r.data["user"]["id"], user.id)

    def test_sms_without_account_finishes_signup(self):
        """A verified new number gets a signed ticket; name + email then creates the account and signs in."""
        with self.assertLogs("accounts.auth_services", level="WARNING") as logs:
            client_for().post(self.request_url, {"phone": "9123456789"})
        r = client_for().post(self.verify_url, {"phone": "9123456789", "code": self._logged_code(logs)})
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.data["register_required"])
        self.assertNotIn("access", r.data)
        register_url = "/api/auth/otp/register/"
        bad = client_for().post(register_url, {"phone_ticket": "forged", "first_name": "A", "email": "a@example.com"})
        self.assertEqual(bad.status_code, 400)
        missing = client_for().post(register_url, {"phone_ticket": r.data["phone_ticket"], "email": "not-an-email"})
        self.assertEqual(missing.status_code, 400)
        self.assertIn("first_name", missing.data)
        self.assertIn("email", missing.data)
        ok = client_for().post(register_url, {"phone_ticket": r.data["phone_ticket"], "first_name": "Asha",
                                              "last_name": "Rao", "email": "Asha@Example.com"})
        self.assertEqual(ok.status_code, 201)
        self.assertIn("access", ok.data)
        user = User.objects.get(email="asha@example.com")
        self.assertEqual(user.phone, "+919123456789")
        again = client_for().post(register_url, {"phone_ticket": r.data["phone_ticket"], "first_name": "X",
                                                 "email": "x@example.com"})
        self.assertEqual(again.status_code, 400)  # number now has an account

    @override_settings(DEBUG=True, SMS_PROVIDER="console")
    def test_dev_code_only_in_debug_without_sms_service(self):
        r = client_for().post(self.request_url, {"phone": "9123400000"})
        self.assertRegex(r.data.get("dev_code", ""), r"^\d{6}$")
        with override_settings(DEBUG=False):
            self.assertNotIn("dev_code", client_for().post(self.request_url, {"phone": "9123400001"}).data)

    def test_needs_exactly_one_destination(self):
        self.assertEqual(client_for().post(self.request_url, {}).status_code, 400)
        r = client_for().post(self.request_url, {"email": "a@example.com", "phone": "9876543210"})
        self.assertEqual(r.status_code, 400)

    @override_settings(OTP_LOGIN_ENABLED=False)
    def test_disabled(self):
        self.assertEqual(client_for().post(self.request_url, {"email": "a@example.com"}).status_code, 400)


class TwoFactorTests(APITestCase):
    def setUp(self):
        super().setUp()
        self.staff = make_staff(email="guard@example.com", password=STRONG)

    def _enable(self):
        c = client_for(self.staff)
        r = c.post("/api/auth/2fa/setup/")
        self.assertEqual(r.status_code, 200, r.data)
        self.assertTrue(r.data["otpauth_uri"].startswith("otpauth://totp/"))
        totp = pyotp.TOTP(r.data["secret"])
        self.assertEqual(c.post("/api/auth/2fa/enable/", {"code": other_code(totp.now())}).status_code, 400)
        r = c.post("/api/auth/2fa/enable/", {"code": totp.now()})
        self.assertEqual(r.status_code, 200, r.data)
        self.assertEqual(len(r.data["backup_codes"]), 10)
        self.staff.refresh_from_db()
        return totp, r.data["backup_codes"]

    def test_visitors_cannot_set_up(self):
        self.assertEqual(client_for(make_visitor()).post("/api/auth/2fa/setup/").status_code, 403)

    def test_secret_never_in_user_payload(self):
        self._enable()
        r = client_for(self.staff).get("/api/auth/me/")
        self.assertTrue(r.data["totp_enabled"])
        self.assertNotIn("totp_secret", r.data)
        self.assertNotIn("totp_backup_codes", r.data)

    def test_login_requires_second_step(self):
        totp, backup = self._enable()
        r = client_for().post("/api/auth/login/", {"email": "guard@example.com", "password": STRONG})
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.data["two_factor_required"])
        self.assertNotIn("access", r.data)
        ticket = r.data["ticket"]
        self.assertEqual(client_for().post("/api/auth/2fa/verify/", {"ticket": ticket, "code": other_code(totp.now())}).status_code, 400)
        r = client_for().post("/api/auth/2fa/verify/", {"ticket": ticket, "code": totp.now()})
        self.assertEqual(r.status_code, 200, r.data)
        self.assertIn("access", r.data)
        r = client_for().post("/api/auth/2fa/verify/", {"ticket": ticket, "code": backup[0]})
        self.assertEqual(r.status_code, 200)
        r = client_for().post("/api/auth/2fa/verify/", {"ticket": ticket, "code": backup[0]})
        self.assertEqual(r.status_code, 400, "backup codes work once")
        self.staff.refresh_from_db()
        self.assertEqual(len(self.staff.totp_backup_codes), 9)

    def test_bad_ticket_rejected(self):
        self._enable()
        r = client_for().post("/api/auth/2fa/verify/", {"ticket": "forged", "code": "123456"})
        self.assertEqual(r.status_code, 400)
        self.assertTrue(r.data["expired"])

    @override_settings(GOOGLE_CLIENT_ID=GOOGLE_ID)
    def test_google_login_also_needs_second_step(self):
        self._enable()
        with mock.patch(VERIFY, return_value=google_claims(email="guard@example.com")):
            r = client_for().post("/api/auth/google/", {"credential": "abc"})
        self.assertTrue(r.data["two_factor_required"])

    def test_disable_with_code(self):
        totp, _ = self._enable()
        c = client_for(self.staff)
        self.assertEqual(c.post("/api/auth/2fa/disable/", {"code": other_code(totp.now())}).status_code, 400)
        self.assertEqual(c.post("/api/auth/2fa/disable/", {"code": totp.now()}).status_code, 200)
        self.staff.refresh_from_db()
        self.assertFalse(self.staff.totp_enabled)
        self.assertEqual(self.staff.totp_secret, "")
        r = client_for().post("/api/auth/login/", {"email": "guard@example.com", "password": STRONG})
        self.assertIn("access", r.data)

    @override_settings(STAFF_2FA_REQUIRED=True)
    def test_setup_required_flag_for_staff_only(self):
        r = client_for().post("/api/auth/login/", {"email": "guard@example.com", "password": STRONG})
        self.assertIn("access", r.data)
        self.assertTrue(r.data["user"]["two_factor_setup_required"])
        self.assertFalse(client_for(make_visitor()).get("/api/auth/me/").data["two_factor_setup_required"])

    def test_login_attempts_are_audited(self):
        client_for().post("/api/auth/login/", {"email": "guard@example.com", "password": "wrong-password"})
        client_for().post("/api/auth/login/", {"email": "guard@example.com", "password": STRONG})
        failed = AuditEntry.objects.get(action="login_failed")
        self.assertEqual(failed.user, self.staff)
        self.assertNotIn("wrong-password", str(failed.changes))
        self.assertTrue(AuditEntry.objects.filter(action="login", user=self.staff).exists())


class UserExportTests(APITestCase):
    url = "/api/auth/users/export/"

    def setUp(self):
        super().setUp()
        self.admin = make_admin()
        self.visitor = make_visitor(first_name="Meera", last_name="Iyer")

    def test_formats_and_filters(self):
        client = client_for(self.admin)
        csv_body = client.get(self.url, {"kind": "csv", "role": "visitor"}).content.decode("utf-8-sig")
        self.assertIn("Meera Iyer", csv_body)
        self.assertNotIn(self.admin.email, csv_body)  # role filter applies
        xlsx = client.get(self.url, {"kind": "xlsx"})
        self.assertEqual(xlsx.status_code, 200)
        self.assertTrue(xlsx.content.startswith(b"PK"))  # a zip-based .xlsx
        pdf = client.get(self.url, {"kind": "pdf", "search": "meera"})
        self.assertEqual(pdf["Content-Type"], "application/pdf")
        self.assertTrue(pdf.content.startswith(b"%PDF"))
        self.assertEqual(client.get(self.url, {"kind": "doc"}).status_code, 400)
        self.assertTrue(AuditEntry.objects.filter(action="users.export").exists())

    def test_admin_only(self):
        self.assertEqual(client_for(self.visitor).get(self.url).status_code, 403)
        self.assertEqual(client_for(make_staff()).get(self.url).status_code, 403)
