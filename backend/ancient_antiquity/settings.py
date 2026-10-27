"""Django settings for the Ancient Antiquity museum booking platform."""
import os
from datetime import timedelta
from pathlib import Path

import dj_database_url
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")


def env_list(name, default=""):
    return [v.strip() for v in os.getenv(name, default).split(",") if v.strip()]


SECRET_KEY = os.getenv("SECRET_KEY", "dev-only-insecure-key")
DEBUG = os.getenv("DEBUG", "True").lower() == "true"
ALLOWED_HOSTS = env_list("ALLOWED_HOSTS", "localhost,127.0.0.1")

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "rest_framework",
    "django_filters",
    "corsheaders",
    "accounts",
    "museums",
    "bookings",
    "notifications",
    "grouprequests",
    "support",
    "promotions",
    "trips",
    "audit",
    "passes",
    "events",
    "partners",
    "assistant",
    "analytics",
    "memberships",
    "schools",
    "donations",
    "addons",
    "demo",
]

MIDDLEWARE = [
    "corsheaders.middleware.CorsMiddleware",
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "audit.middleware.AuditMiddleware",  # records staff/admin changes made through the API
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "ancient_antiquity.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

WSGI_APPLICATION = "ancient_antiquity.wsgi.application"

DATABASES = {
    "default": dj_database_url.config(
        default=os.getenv(
            "DATABASE_URL",
            "postgres://postgres:postgres@localhost:5432/ancient_antiquity",
        ),
        conn_max_age=600,
    )
}

AUTH_USER_MODEL = "accounts.User"

# Passwords are never stored in plain text: Django keeps a salted, one-way hash.
# Argon2id (winner of the Password Hashing Competition) is used for new passwords;
# older PBKDF2 hashes are upgraded to Argon2 automatically the next time that user logs in.
PASSWORD_HASHERS = [
    "django.contrib.auth.hashers.Argon2PasswordHasher",
    "django.contrib.auth.hashers.PBKDF2PasswordHasher",
    "django.contrib.auth.hashers.PBKDF2SHA1PasswordHasher",
    "django.contrib.auth.hashers.ScryptPasswordHasher",
]

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

LANGUAGE_CODE = "en-in"
TIME_ZONE = "Asia/Kolkata"
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"

# Uploaded files (place photos uploaded by admins)
MEDIA_URL = "/media/"
MEDIA_ROOT = Path(os.getenv("MEDIA_ROOT", str(BASE_DIR / "media")))
MAX_UPLOAD_MB = int(os.getenv("MAX_UPLOAD_MB", "8"))

# Public address of the React site, used in emails (ticket links, password reset)
FRONTEND_URL = os.getenv("FRONTEND_URL", "http://127.0.0.1:5173").rstrip("/")

# Email: printed to the console in development; set EMAIL_HOST etc. for real sending (SMTP, e.g. SES/SendGrid/Gmail)
REAL_EMAIL_BACKEND = os.getenv(
    "EMAIL_BACKEND",
    "django.core.mail.backends.smtp.EmailBackend" if os.getenv("EMAIL_HOST") else "django.core.mail.backends.console.EmailBackend",
)
# Every email passes through this guard first: it drops sample-data accounts (User.is_sample), whose made-up
# addresses may belong to real people, then hands the rest to REAL_EMAIL_BACKEND.
EMAIL_BACKEND = "notifications.mail.SampleSafeEmailBackend"
# With the file backend every email is saved as a .log file here (development / no SMTP account yet).
EMAIL_FILE_PATH = os.getenv("EMAIL_FILE_PATH", str(BASE_DIR / "sent_emails"))
EMAIL_HOST = os.getenv("EMAIL_HOST", "")
EMAIL_PORT = int(os.getenv("EMAIL_PORT", "587"))
EMAIL_HOST_USER = os.getenv("EMAIL_HOST_USER", "")
EMAIL_HOST_PASSWORD = os.getenv("EMAIL_HOST_PASSWORD", "")
EMAIL_USE_TLS = os.getenv("EMAIL_USE_TLS", "True").lower() == "true"
DEFAULT_FROM_EMAIL = os.getenv("DEFAULT_FROM_EMAIL", "Ancient Antiquity <tickets@ancientantiquity.in>")
SUPPORT_EMAIL = os.getenv("SUPPORT_EMAIL", "support@ancientantiquity.in")
SUPPORT_PHONE = os.getenv("SUPPORT_PHONE", "")

# SMS / WhatsApp: "console" (log only) unless a provider is configured
SMS_PROVIDER = os.getenv("SMS_PROVIDER", "console")  # console | msg91 | twilio
SMS_API_KEY = os.getenv("SMS_API_KEY", "")
SMS_SENDER_ID = os.getenv("SMS_SENDER_ID", "ANCANT")
TWILIO_ACCOUNT_SID = os.getenv("TWILIO_ACCOUNT_SID", "")
TWILIO_AUTH_TOKEN = os.getenv("TWILIO_AUTH_TOKEN", "")
TWILIO_FROM = os.getenv("TWILIO_FROM", "")

# Social / passwordless login (all optional; a method is hidden in the UI until configured)
GOOGLE_MAPS_API_KEY = os.getenv("GOOGLE_MAPS_API_KEY", "")  # Places API (New): photos for places without one
GOOGLE_PHOTO_CACHE_HOURS = int(os.getenv("GOOGLE_PHOTO_CACHE_HOURS", "12"))
GOOGLE_CLIENT_ID = os.getenv("GOOGLE_CLIENT_ID", "")  # Google Cloud Console -> Credentials -> OAuth client (Web)
OTP_LOGIN_ENABLED = os.getenv("OTP_LOGIN_ENABLED", "True").lower() == "true"  # email/mobile one-time codes
OTP_TTL_MINUTES = int(os.getenv("OTP_TTL_MINUTES", "10"))
STAFF_2FA_REQUIRED = os.getenv("STAFF_2FA_REQUIRED", "False").lower() == "true"  # force 2FA for staff/admins

# Web push (visit reminders). Generate keys once: see DEPLOY.md / notifications README
VAPID_PUBLIC_KEY = os.getenv("VAPID_PUBLIC_KEY", "")
VAPID_PRIVATE_KEY = os.getenv("VAPID_PRIVATE_KEY", "")
VAPID_SUBJECT = os.getenv("VAPID_SUBJECT", "mailto:support@ancientantiquity.in")

# WhatsApp tickets/reminders (optional): "console" logs only; "meta" = WhatsApp Cloud API
WHATSAPP_PROVIDER = os.getenv("WHATSAPP_PROVIDER", "console")
WHATSAPP_TOKEN = os.getenv("WHATSAPP_TOKEN", "")
WHATSAPP_PHONE_NUMBER_ID = os.getenv("WHATSAPP_PHONE_NUMBER_ID", "")

# AI visitor assistant (optional; hidden until ANTHROPIC_API_KEY is set)
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
ASSISTANT_MODEL = os.getenv("ASSISTANT_MODEL", "")  # empty = the assistant app's default model
ASSISTANT_DAILY_MESSAGE_LIMIT = int(os.getenv("ASSISTANT_DAILY_MESSAGE_LIMIT", "40"))  # per visitor/IP

# Donations (restoration fund). 80G receipts need the trust's registration details.
DONATION_80G_NUMBER = os.getenv("DONATION_80G_NUMBER", "")
DONATION_TRUST_NAME = os.getenv("DONATION_TRUST_NAME", "")
DONATION_TRUST_PAN = os.getenv("DONATION_TRUST_PAN", "")

# Approximate foreign-currency display (prices are always charged in INR). Units of currency per 1 INR.
FX_RATES = os.getenv("FX_RATES", "USD=0.012,EUR=0.011,GBP=0.0095")

# Error monitoring (optional)
SENTRY_DSN = os.getenv("SENTRY_DSN", "")
from .monitoring import init_sentry  # noqa: E402  (does nothing unless SENTRY_DSN is set)

init_sentry(SENTRY_DSN)

# Business details printed on GST invoices (fill in before going live)
INVOICE_SELLER_NAME = os.getenv("INVOICE_SELLER_NAME", "Ancient Antiquity [legal entity name]")
INVOICE_SELLER_ADDRESS = os.getenv("INVOICE_SELLER_ADDRESS", "[Registered address]")
INVOICE_SELLER_GSTIN = os.getenv("INVOICE_SELLER_GSTIN", "")
INVOICE_GST_PERCENT = float(os.getenv("INVOICE_GST_PERCENT", "18"))

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

CORS_ALLOWED_ORIGINS = env_list(
    "CORS_ALLOWED_ORIGINS", "http://localhost:5173,http://127.0.0.1:5173"
)

# The React dev server proxies /django-admin, so its origin must be trusted for admin form posts.
CSRF_TRUSTED_ORIGINS = env_list(
    "CSRF_TRUSTED_ORIGINS",
    "http://localhost:5173,http://127.0.0.1:5173,http://localhost:8000,http://127.0.0.1:8000",
)

REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": (
        "rest_framework_simplejwt.authentication.JWTAuthentication",
    ),
    "DEFAULT_PERMISSION_CLASSES": ("rest_framework.permissions.IsAuthenticated",),
    "DEFAULT_FILTER_BACKENDS": (
        "django_filters.rest_framework.DjangoFilterBackend",
        "rest_framework.filters.SearchFilter",
        "rest_framework.filters.OrderingFilter",
    ),
    "DEFAULT_PAGINATION_CLASS": "rest_framework.pagination.PageNumberPagination",
    "PAGE_SIZE": 12,
}

SIMPLE_JWT = {
    "ACCESS_TOKEN_LIFETIME": timedelta(minutes=60),
    "REFRESH_TOKEN_LIFETIME": timedelta(days=7),
    "ROTATE_REFRESH_TOKENS": True,
    "UPDATE_LAST_LOGIN": True,  # record website logins in the user's "last login"
}

BOOKING_HOLD_MINUTES = int(os.getenv("BOOKING_HOLD_MINUTES", "15"))
BOOKING_WINDOW_DAYS = int(os.getenv("BOOKING_WINDOW_DAYS", "90"))
MAX_TICKETS_PER_BOOKING = 20

# Payments: Razorpay is used when both keys are set; otherwise the demo gateway is used.
# Keys come from https://dashboard.razorpay.com -> Account & Settings -> API Keys (test keys start rzp_test_).
RAZORPAY_KEY_ID = os.getenv("RAZORPAY_KEY_ID", "")
RAZORPAY_KEY_SECRET = os.getenv("RAZORPAY_KEY_SECRET", "")
RAZORPAY_WEBHOOK_SECRET = os.getenv("RAZORPAY_WEBHOOK_SECRET", "")
# Refund policy: full refund when cancelled at least this many hours before the visit slot, otherwise none.
REFUND_FULL_BEFORE_HOURS = int(os.getenv("REFUND_FULL_BEFORE_HOURS", "24"))

# Group bookings (schools, tour operators, companies...)
GROUP_MIN_SIZE = 21  # paying participants; smaller parties book normally
GROUP_MAX_SIZE = 60  # larger groups need a manual arrangement
GROUP_SLOT_SHARE = 0.30  # groups may fill at most this share of a slot, keeping room for individuals/walk-ins
GROUP_ESCORTS_PER = 10  # school/college groups: one free escort (teacher) per this many students

ADMIN_SITE_HEADER = "Ancient Antiquity Administration"


# =====================================================================================================
# PRODUCTION / DEPLOYMENT  (support + deployment block - keep this block at the very END of the file)
# Everything below only tightens settings defined above; in development (DEBUG=True) it changes almost
# nothing except adding WhiteNoise and console logging. See DEPLOY.md.
# =====================================================================================================
import tempfile  # noqa: E402

from django.core.exceptions import ImproperlyConfigured  # noqa: E402

# WhiteNoise serves /static/ (Django admin CSS/JS) straight from gunicorn, right after SecurityMiddleware.
if "whitenoise.middleware.WhiteNoiseMiddleware" not in MIDDLEWARE:
    MIDDLEWARE.insert(
        MIDDLEWARE.index("django.middleware.security.SecurityMiddleware") + 1,
        "whitenoise.middleware.WhiteNoiseMiddleware",
    )

STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    # Hashed + compressed file names in production (needs `collectstatic`); plain storage in development.
    "staticfiles": {
        "BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"
        if DEBUG
        else "whitenoise.storage.CompressedManifestStaticFilesStorage"
    },
}

# Re-validate pooled DB connections (conn_max_age=600 above) so a restarted Postgres doesn't cause errors.
DATABASES["default"]["CONN_HEALTH_CHECKS"] = True
if DATABASES["default"]["ENGINE"].endswith("sqlite3"):
    # WAL lets admin pages read while bookings are being written (the default journal locks readers out),
    # and a bigger page cache keeps the hot booking indexes in memory. Postgres needs none of this.
    DATABASES["default"].setdefault("OPTIONS", {}).update({
        "timeout": 20,  # wait for a busy database instead of failing with "database is locked"
        "init_command": (
            "PRAGMA journal_mode=WAL; PRAGMA synchronous=NORMAL; PRAGMA cache_size=-65536; "
            "PRAGMA temp_store=MEMORY; PRAGMA mmap_size=268435456;"
        ),
    })

LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()
LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {"plain": {"format": "%(asctime)s %(levelname)s %(name)s: %(message)s"}},
    "handlers": {"console": {"class": "logging.StreamHandler", "formatter": "plain"}},
    "root": {"handlers": ["console"], "level": LOG_LEVEL},
    "loggers": {
        "django": {"handlers": ["console"], "level": LOG_LEVEL, "propagate": False},
        # 4xx/5xx request errors (with tracebacks for 500s)
        "django.request": {"handlers": ["console"], "level": "WARNING", "propagate": False},
        "django.security": {"handlers": ["console"], "level": "WARNING", "propagate": False},
    },
}

if not DEBUG:
    _DEV_SECRET_KEYS = {"", "dev-only-insecure-key", "change-me-in-production"}
    if SECRET_KEY in _DEV_SECRET_KEYS or len(SECRET_KEY) < 40:
        raise ImproperlyConfigured(
            "DEBUG is False but SECRET_KEY is missing, a development default or too short. Generate one with: "
            "python -c \"import secrets; print(secrets.token_urlsafe(50))\" and set SECRET_KEY in the environment."
        )

    # nginx terminates HTTPS and forwards the original scheme in X-Forwarded-Proto.
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
    SECURE_SSL_REDIRECT = os.getenv("SECURE_SSL_REDIRECT", "True").lower() == "true"
    SECURE_REDIRECT_EXEMPT = [r"^api/support/health/$"]  # container / uptime health checks over plain http
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True
    SESSION_COOKIE_HTTPONLY = True
    # HSTS: start small (1 hour), raise to 31536000 (1 year) once HTTPS is confirmed working everywhere.
    SECURE_HSTS_SECONDS = int(os.getenv("SECURE_HSTS_SECONDS", "3600"))
    SECURE_HSTS_INCLUDE_SUBDOMAINS = os.getenv("SECURE_HSTS_INCLUDE_SUBDOMAINS", "False").lower() == "true"
    SECURE_HSTS_PRELOAD = os.getenv("SECURE_HSTS_PRELOAD", "False").lower() == "true"
    SECURE_CONTENT_TYPE_NOSNIFF = True
    SECURE_REFERRER_POLICY = "strict-origin-when-cross-origin"
    X_FRAME_OPTIONS = "DENY"

    # Cache shared by all gunicorn workers in a container (used by API rate limits such as the contact form).
    CACHES = {
        "default": {
            "BACKEND": "django.core.cache.backends.filebased.FileBasedCache",
            "LOCATION": os.getenv("CACHE_DIR", os.path.join(tempfile.gettempdir(), "ancient_antiquity_cache")),
        }
    }

    # Unhandled 500 errors are emailed to these addresses (comma separated) when SMTP is configured.
    ADMINS = [("Admin", e) for e in env_list("ADMIN_EMAILS")]
    SERVER_EMAIL = os.getenv("SERVER_EMAIL", DEFAULT_FROM_EMAIL)
# ======================================= end of production block =====================================

# --- stats/exports ---
# Pre-calculated daily booking statistics (stats.DailyStat) and background export jobs (stats.ExportJob).
INSTALLED_APPS += ["stats"]
STATS_FRESH_SECONDS = int(os.getenv("STATS_FRESH_SECONDS", "120"))  # today/yesterday are recomputed when older
# Export files are private (served only through the authenticated download endpoint), so NOT under MEDIA_ROOT.
EXPORTS_DIR = Path(os.getenv("EXPORTS_DIR", str(BASE_DIR / "exports")))
EXPORT_KEEP_DAYS = int(os.getenv("EXPORT_KEEP_DAYS", "7"))
EXPORT_PDF_MAX_ROWS = int(os.getenv("EXPORT_PDF_MAX_ROWS", "5000"))
EXPORT_XLSX_SHEET_ROWS = 1_000_000  # Excel's limit is 1,048,576 rows per sheet; larger exports continue on more sheets
EXPORT_RUN_INLINE = False  # tests set True: run the job in the request instead of a background thread
# --- end stats/exports ---

# --- insights ---
# Pricing suggestions for the admin panel (backend/insights; its urls are included in ancient_antiquity/urls.py).
INSTALLED_APPS += ["insights"]
# --- end insights ---
