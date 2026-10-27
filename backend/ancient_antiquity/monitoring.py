"""Error alerts via Sentry (optional).

Enabled only when SENTRY_DSN is set. Call from settings.py after SENTRY_DSN is defined:

    from .monitoring import init_sentry
    init_sentry(SENTRY_DSN)
"""
import os


def init_sentry(dsn=None, environment=None, release=None):
    """Initialise sentry-sdk with the Django integration. Returns True when Sentry was enabled."""
    dsn = dsn if dsn is not None else os.getenv("SENTRY_DSN", "")
    if not dsn:
        return False
    import sentry_sdk
    from sentry_sdk.integrations.django import DjangoIntegration

    sentry_sdk.init(
        dsn=dsn,
        integrations=[DjangoIntegration()],
        traces_sample_rate=0.1,     # 10% of requests traced for performance monitoring
        send_default_pii=False,     # no user emails/IPs/cookies sent to Sentry
        environment=environment or os.getenv("SENTRY_ENVIRONMENT", "production"),
        release=release or os.getenv("SENTRY_RELEASE") or None,
    )
    return True
