"""Sign-in helpers: token responses, Google ID tokens, one-time login codes and two-step verification."""
import logging
import re
import secrets
from datetime import timedelta

import pyotp
from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.models import update_last_login
from django.core import signing
from django.core.mail import send_mail
from django.template.loader import render_to_string
from django.utils import timezone
from django.utils.crypto import constant_time_compare, salted_hmac
from rest_framework_simplejwt.tokens import RefreshToken

from audit.services import record

from .models import LoginOTP

logger = logging.getLogger(__name__)
User = get_user_model()

TICKET_SALT = "accounts.2fa.ticket"
TICKET_MAX_AGE = 300  # seconds
OTP_MAX_ATTEMPTS = 5
OTP_PER_DESTINATION = 3  # codes per destination ...
OTP_WINDOW = timedelta(minutes=10)  # ... per this window
BACKUP_CODE_COUNT = 10
TOTP_ISSUER = "Ancient Antiquity"


# ------------------------------------------------------------------ token responses

def token_payload(user):
    from .serializers import UserSerializer

    refresh = RefreshToken.for_user(user)
    if settings.SIMPLE_JWT.get("UPDATE_LAST_LOGIN"):
        update_last_login(None, user)
    return {"access": str(refresh.access_token), "refresh": str(refresh), "user": UserSerializer(user).data}


def make_ticket(user, method):
    return signing.dumps({"uid": user.pk, "m": method}, salt=TICKET_SALT)


def read_ticket(ticket):
    """(user, method) for a valid, unexpired ticket, else (None, None)."""
    try:
        data = signing.loads(ticket or "", salt=TICKET_SALT, max_age=TICKET_MAX_AGE)
    except signing.BadSignature:  # includes SignatureExpired
        return None, None
    user = User.objects.filter(pk=data.get("uid"), is_active=True).first()
    return user, data.get("m", "")


def complete_login(request, user, method):
    """Tokens for the user, or a two-step challenge when they have an authenticator app set up."""
    if user.totp_enabled and user.totp_secret:
        return {"two_factor_required": True, "ticket": make_ticket(user, method)}
    record(request, "login", user=user, object_repr=user.email, status_code=200, changes={"method": method})
    return token_payload(user)


def login_failed(request, identifier, method, reason=""):
    user = User.objects.filter(email__iexact=identifier).first() if identifier and "@" in identifier else None
    record(request, "login_failed", user=user, object_repr=identifier or "", status_code=400,
           changes={"method": method, "reason": reason})


# ------------------------------------------------------------------ Google

def verify_google_credential(credential):
    """Claims of a Google ID token issued for our client id. Raises ValueError when invalid."""
    from google.auth.transport import requests as google_requests
    from google.oauth2 import id_token

    if not settings.GOOGLE_CLIENT_ID:
        raise ValueError("Google sign-in is not configured.")
    return id_token.verify_oauth2_token(credential, google_requests.Request(), settings.GOOGLE_CLIENT_ID)


def user_for_google(claims):
    """Existing user (linked on first use) or a new visitor account. Returns (user, created)."""
    sub = str(claims.get("sub") or "")
    email = (claims.get("email") or "").strip().lower()
    user = User.objects.filter(google_sub=sub).first() if sub else None
    if user is None and email:
        user = User.objects.filter(email__iexact=email).first()
    if user is not None:
        if sub and user.google_sub != sub:
            user.google_sub = sub
            user.save(update_fields=["google_sub"])
        return user, False
    user = User.objects.create_user(
        email=email,
        password=None,  # unusable: they sign in with Google (or reset a password later)
        first_name=(claims.get("given_name") or "")[:150],
        last_name=(claims.get("family_name") or "")[:150],
        google_sub=sub,
    )
    return user, True


# ------------------------------------------------------------------ one-time login codes

def normalise_phone(phone):
    """Digits with country code (Indian 10-digit numbers get 91 prefixed)."""
    digits = re.sub(r"\D", "", phone or "")
    if len(digits) == 11 and digits.startswith("0"):
        digits = digits[1:]
    if len(digits) == 10:
        digits = "91" + digits
    return digits


def user_for_phone(number):
    """Active user whose stored phone normalises to `number` (phones are stored as typed)."""
    if len(number) < 10:
        return None
    for user in User.objects.filter(phone__contains=number[-4:], is_active=True).order_by("date_joined"):
        if normalise_phone(user.phone) == number:
            return user
    return None


def _hash(purpose, value):
    return salted_hmac(f"accounts.{purpose}", value).hexdigest()


def sms_available():
    from notifications.services import _provider_ready

    provider = (settings.SMS_PROVIDER or "console").lower()
    return _provider_ready(provider) or (provider == "console" and settings.DEBUG)


def methods():
    return {
        "google_client_id": settings.GOOGLE_CLIENT_ID or None,
        "otp_email": bool(settings.OTP_LOGIN_ENABLED),
        "otp_sms": bool(settings.OTP_LOGIN_ENABLED and sms_available()),
        "password": True,
    }


def dev_code_visible(channel):
    """Development only: show the code on screen when it can't actually be delivered (no SMS/email service)."""
    if not settings.DEBUG:
        return False
    if channel == LoginOTP.Channel.SMS:
        return (settings.SMS_PROVIDER or "console").lower() == "console"
    backend = settings.EMAIL_BACKEND
    if backend == "notifications.mail.SampleSafeEmailBackend":
        backend = getattr(settings, "REAL_EMAIL_BACKEND", backend)  # the guard wraps the real backend
    return any(name in backend for name in ("console", "locmem", "filebased"))


def issue_otp(destination, channel):
    """Create and send a code unless the destination hit its limit. Returns the code, or None when not sent."""
    since = timezone.now() - OTP_WINDOW
    if LoginOTP.objects.filter(destination=destination, channel=channel, created_at__gte=since).count() >= OTP_PER_DESTINATION:
        logger.info("Login code limit reached for %s", destination)
        return None
    code = f"{secrets.randbelow(10**6):06d}"
    LoginOTP.objects.filter(destination=destination, channel=channel, used_at__isnull=True).update(used_at=timezone.now())
    LoginOTP.objects.create(
        destination=destination,
        channel=channel,
        code_hash=_hash("otp", f"{channel}:{destination}:{code}"),
        expires_at=timezone.now() + timedelta(minutes=settings.OTP_TTL_MINUTES),
    )
    if settings.DEBUG:
        logger.warning("DEBUG login code for %s: %s", destination, code)
    if channel == LoginOTP.Channel.EMAIL:
        _send_code_email(destination, code)
    else:
        _send_code_sms(destination, code)
    return code


PHONE_SIGNUP_SALT = "accounts.phone-signup"
PHONE_SIGNUP_MAX_AGE = 15 * 60  # seconds to finish creating the account after verifying the code


def make_phone_signup_ticket(number):
    """Signed proof that this mobile number was just verified by code (used to finish sign-up)."""
    return signing.dumps({"phone": number}, salt=PHONE_SIGNUP_SALT)


def read_phone_signup_ticket(ticket):
    try:
        return signing.loads(ticket, salt=PHONE_SIGNUP_SALT, max_age=PHONE_SIGNUP_MAX_AGE).get("phone")
    except signing.BadSignature:
        return None


def check_otp(destination, channel, code):
    """(True, "") when the code matches the latest live code; otherwise (False, message)."""
    otp = LoginOTP.objects.filter(
        destination=destination, channel=channel, used_at__isnull=True, expires_at__gt=timezone.now()
    ).first()
    if otp is None:
        return False, "This code has expired or is not valid. Please request a new one."
    if otp.attempts >= OTP_MAX_ATTEMPTS:
        return False, "Too many wrong attempts. Please request a new code."
    expected = _hash("otp", f"{channel}:{destination}:{(code or '').strip()}")
    if not constant_time_compare(expected, otp.code_hash):
        otp.attempts += 1
        otp.save(update_fields=["attempts"])
        left = OTP_MAX_ATTEMPTS - otp.attempts
        if left <= 0:
            return False, "Too many wrong attempts. Please request a new code."
        return False, f"That code is not correct. {left} attempt(s) left."
    otp.used_at = timezone.now()
    otp.save(update_fields=["used_at"])
    return True, ""


def _send_code_email(email, code):
    context = {"code": code, "minutes": settings.OTP_TTL_MINUTES}
    try:
        send_mail(
            f"{code} is your Ancient Antiquity sign-in code",
            render_to_string("accounts/login_code_email.txt", context),
            None,
            [email],
        )
    except Exception:
        logger.exception("Could not email a sign-in code to %s", email)


def _send_code_sms(number, code):
    """Send through the configured SMS provider. The NotificationLog row never contains the code."""
    from notifications.models import NotificationLog
    from notifications.services import _log, _provider_ready, _send_msg91, _send_twilio

    text = f"{code} is your Ancient Antiquity sign-in code. It expires in {settings.OTP_TTL_MINUTES} minutes. Do not share it."
    base = dict(channel=NotificationLog.Channel.SMS, kind="login_code", subject="Sign-in code (hidden)", recipient=number)
    provider = (settings.SMS_PROVIDER or "console").lower()
    try:
        if provider in ("msg91", "twilio") and _provider_ready(provider):
            (_send_msg91 if provider == "msg91" else _send_twilio)(number, text)
        else:
            logger.info("SMS sign-in code to +%s (console mode, not sent)", number)
            return _log(**base, status=NotificationLog.Status.SKIPPED, error="Console mode; not sent")
    except Exception as exc:
        logger.exception("Sign-in code SMS to %s failed", number)
        return _log(**base, status=NotificationLog.Status.FAILED, error=str(exc)[:2000])
    return _log(**base, status=NotificationLog.Status.SENT)


# ------------------------------------------------------------------ two-step verification (TOTP)

def totp_uri(user):
    return pyotp.TOTP(user.totp_secret).provisioning_uri(name=user.email, issuer_name=TOTP_ISSUER)


def new_backup_codes(user):
    """Replace the user's backup codes; returns the plain codes (shown once)."""
    codes = [f"{secrets.token_hex(2)}-{secrets.token_hex(2)}" for _ in range(BACKUP_CODE_COUNT)]
    user.totp_backup_codes = [_hash("backup", f"{user.pk}:{c}") for c in codes]
    return codes


def verify_second_factor(user, code, allow_backup=True):
    """Check an authenticator code (or, if allowed, consume a backup code). Saves the user on backup use."""
    code = (code or "").strip().lower().replace(" ", "")
    if not code or not user.totp_secret:
        return False
    if code.isdigit() and len(code) == 6 and pyotp.TOTP(user.totp_secret).verify(code, valid_window=1):
        return True
    if allow_backup:
        if len(code) == 8 and "-" not in code:
            code = f"{code[:4]}-{code[4:]}"
        hashed = _hash("backup", f"{user.pk}:{code}")
        for stored in list(user.totp_backup_codes or []):
            if constant_time_compare(stored, hashed):
                user.totp_backup_codes = [c for c in user.totp_backup_codes if c != stored]
                user.save(update_fields=["totp_backup_codes"])
                return True
    return False


def two_factor_setup_required(user):
    return bool(settings.STAFF_2FA_REQUIRED and user.is_panel_user and not user.totp_enabled)
