import hashlib

from django.conf import settings
from django.db.models import Q
from django.utils import timezone
from rest_framework import permissions, status
from rest_framework.response import Response
from rest_framework.throttling import BaseThrottle
from rest_framework.views import APIView

from . import service
from .models import AssistantLog


def client_ip_hash(request):
    """Salted hash of the client IP: enough to count messages per visitor without storing the address."""
    ip = BaseThrottle().get_ident(request) or ""
    return hashlib.sha256(f"{settings.SECRET_KEY}|assistant|{ip}".encode()).hexdigest()


def _user(request):
    return request.user if request.user and request.user.is_authenticated else None


def messages_used_today(request):
    start = timezone.localtime().replace(hour=0, minute=0, second=0, microsecond=0)
    user = _user(request)
    who = Q(user=user) if user is not None else Q(ip_hash=client_ip_hash(request), user__isnull=True)
    return AssistantLog.objects.filter(who, created_at__gte=start).count()


def _status_payload(request):
    limit = settings.ASSISTANT_DAILY_MESSAGE_LIMIT
    if not service.is_available():
        return {"available": False}
    used = messages_used_today(request)
    return {"available": True, "daily_limit": limit, "remaining": max(limit - used, 0)}


class AssistantStatusView(APIView):
    """GET /api/assistant/status/ - whether the chat widget should be shown, and the visitor's remaining messages."""

    permission_classes = [permissions.AllowAny]

    def get(self, request):
        return Response(_status_payload(request))


class AssistantChatView(APIView):
    """POST /api/assistant/chat/ {messages: [{role, content}], lang, page_context?} -> {reply, links, remaining}."""

    permission_classes = [permissions.AllowAny]

    def post(self, request):
        if not service.is_available():
            return Response({"available": False, "detail": "The assistant is not available."},
                            status=status.HTTP_503_SERVICE_UNAVAILABLE)
        limit = settings.ASSISTANT_DAILY_MESSAGE_LIMIT
        used = messages_used_today(request)
        if used >= limit:
            return Response(
                {"available": True, "limit_reached": True, "remaining": 0,
                 "detail": "You have reached today's message limit for the assistant. Please try again tomorrow."},
                status=status.HTTP_429_TOO_MANY_REQUESTS,
            )
        try:
            messages = service.clean_messages(request.data.get("messages"))
        except ValueError as exc:
            return Response({"messages": [str(exc)]}, status=status.HTTP_400_BAD_REQUEST)
        lang = "hi" if request.data.get("lang") == "hi" else "en"
        page_context = request.data.get("page_context")
        user = _user(request)
        ip_hash = client_ip_hash(request)

        try:
            result = service.chat(messages, lang=lang, page_context=page_context, user=user)
        except service.AssistantError as exc:
            AssistantLog.objects.create(user=user, ip_hash=ip_hash, lang=lang, model=service.model_name(),
                                        outcome=AssistantLog.Outcome.ERROR)
            return Response({"detail": str(exc)}, status=exc.status)

        usage = result["usage"]
        AssistantLog.objects.create(
            user=user, ip_hash=ip_hash, lang=lang, model=result["model"], outcome=result["outcome"],
            tokens_in=usage["in"], tokens_out=usage["out"], cache_read_tokens=usage["cache_read"],
            cache_write_tokens=usage["cache_write"], tool_calls=min(result["tool_calls"], 32767),
        )
        return Response({
            "reply": result["reply"],
            "links": result["links"],
            "remaining": max(limit - used - 1, 0),
        })
