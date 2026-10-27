"""Records changes that staff and administrators make through the API.

Enable by adding "audit.middleware.AuditMiddleware" to MIDDLEWARE (after AuthenticationMiddleware).
API requests authenticate with JWT inside the DRF view, and DRF copies the user onto the Django request,
so the user is read *after* the view has run.
"""
import json

from .services import record

WRITE_METHODS = {"POST", "PUT", "PATCH", "DELETE"}
API_PREFIX = "/api/"
# Sign-in endpoints log their own (sanitised) login/login_failed entries; token refresh is noise.
EXCLUDED_PREFIXES = (
    "/api/auth/login/",
    "/api/auth/register/",
    "/api/auth/refresh/",
    "/api/auth/google/",
    "/api/auth/otp/",
    "/api/auth/2fa/verify/",
    "/api/auth/password-reset/",
)
MAX_BODY_BYTES = 64 * 1024
REPR_FIELDS = ("reference", "name", "title", "email", "slug", "id")


def _json_body(request):
    """Parse a small JSON body before the view reads the stream (Django caches it for the view)."""
    if "json" not in (request.content_type or ""):
        return None
    try:
        length = int(request.META.get("CONTENT_LENGTH") or 0)
    except ValueError:
        return None
    if length <= 0 or length > MAX_BODY_BYTES:
        return {"_note": "body not recorded (empty or too large)"} if length else None
    try:
        return json.loads(request.body.decode("utf-8") or "null")
    except (ValueError, UnicodeDecodeError):
        return {"_note": "invalid JSON body"}


def _form_body(request):
    """Form / multipart data as parsed by DRF (files are listed by name only)."""
    data = {}
    try:
        post = getattr(request, "_post", None)
        if post is not None:
            for key in post.keys():
                values = post.getlist(key)
                data[key] = values[0] if len(values) == 1 else values
        files = getattr(request, "_files", None)
        if files:
            for key in files.keys():
                data[key] = [f"<file {f.name}>" for f in files.getlist(key)]
    except Exception:
        return {}
    return data


def _object_repr(response, path):
    payload = getattr(response, "data", None)
    if isinstance(payload, dict):
        for field in REPR_FIELDS:
            value = payload.get(field)
            if value not in (None, ""):
                return f"{field}: {value}"
    return path


def _action(method, status_code):
    if method == "POST":
        return "create" if status_code == 201 else "other"
    if method in ("PUT", "PATCH"):
        return "update"
    if method == "DELETE":
        return "delete"
    return "other"


class AuditMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        path = request.path
        watch = (
            request.method in WRITE_METHODS
            and path.startswith(API_PREFIX)
            and not path.startswith(EXCLUDED_PREFIXES)
        )
        body = _json_body(request) if watch else None
        response = self.get_response(request)
        if not watch:
            return response
        user = getattr(request, "user", None)
        if not (user and user.is_authenticated and getattr(user, "is_panel_user", False)):
            return response
        if body is None and "json" not in (request.content_type or ""):
            body = _form_body(request)
        record(
            request,
            _action(request.method, response.status_code),
            user=user,
            object_repr=_object_repr(response, path),
            status_code=response.status_code,
            changes=body if isinstance(body, dict) else {"body": body} if body is not None else {},
        )
        return response
