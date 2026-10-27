"""Helpers to write audit entries. Writing the log must never break the request that is being logged."""
import ipaddress
import logging
import re

from .models import AuditEntry

logger = logging.getLogger(__name__)

# A key is secret when any of its words (split on _ - . and camelCase) is one of these.
SECRET_WORDS = {
    "password", "password1", "password2", "passwd", "token", "code", "credential", "credentials",
    "secret", "signature", "refresh", "access", "otp", "ticket", "pin", "cvv", "authorization",
}
REDACTED = "***"
MAX_STRING = 500
MAX_ITEMS = 50


def _is_secret(key):
    words = re.split(r"[_\-.\s]+", re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", str(key)))
    return any(w.lower() in SECRET_WORDS for w in words if w)


def sanitize(value, depth=0):
    """Copy of request data that is safe to store: secret-looking keys masked, long values trimmed."""
    if depth > 6:
        return "…"
    if isinstance(value, dict):
        out = {}
        for i, (k, v) in enumerate(value.items()):
            if i >= MAX_ITEMS:
                out["…"] = f"{len(value) - MAX_ITEMS} more"
                break
            out[str(k)] = REDACTED if _is_secret(k) else sanitize(v, depth + 1)
        return out
    if isinstance(value, (list, tuple)):
        items = [sanitize(v, depth + 1) for v in list(value)[:MAX_ITEMS]]
        if len(value) > MAX_ITEMS:
            items.append(f"… {len(value) - MAX_ITEMS} more")
        return items
    if isinstance(value, str):
        return value if len(value) <= MAX_STRING else value[:MAX_STRING] + "…"
    if value is None or isinstance(value, (bool, int, float)):
        return value
    return str(value)[:MAX_STRING]


def client_ip(request):
    forwarded = request.META.get("HTTP_X_FORWARDED_FOR", "")
    ip = forwarded.split(",")[0].strip() if forwarded else request.META.get("REMOTE_ADDR", "")
    try:
        return str(ipaddress.ip_address(ip))
    except ValueError:
        return None


def record(request, action, *, user=None, object_repr="", status_code=None, changes=None):
    """Write one AuditEntry; errors are logged, never raised."""
    try:
        if user is not None and not getattr(user, "is_authenticated", False):
            user = None
        return AuditEntry.objects.create(
            user=user,
            ip=client_ip(request) if request is not None else None,
            method=(request.method if request is not None else "")[:10],
            path=(request.path if request is not None else "")[:500],
            action=action,
            object_repr=str(object_repr or "")[:255],
            status_code=status_code,
            changes=sanitize(changes or {}),
        )
    except Exception:  # pragma: no cover - DB problems must not break sign-in or saving
        logger.exception("Could not write audit entry (%s %s)", action, object_repr)
        return None
