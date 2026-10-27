import logging

from django.conf import settings
from django.core.mail import send_mail
from django.db import connection
from rest_framework import generics, mixins, status, viewsets
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.throttling import AnonRateThrottle
from rest_framework.views import APIView

from accounts.permissions import IsPanelUser

from .models import ContactMessage
from .serializers import AdminContactMessageSerializer, ContactMessageCreateSerializer

logger = logging.getLogger(__name__)


class ContactThrottle(AnonRateThrottle):
    """At most 5 contact-form posts per hour per client IP (signed-in visitors included)."""

    scope = "support_contact"
    rate = "5/hour"

    def get_cache_key(self, request, view):
        return self.cache_format % {"scope": self.scope, "ident": self.get_ident(request)}


class HealthView(APIView):
    """Liveness/readiness for Docker, load balancers and uptime monitors: 200 when the database answers."""

    permission_classes = [AllowAny]
    authentication_classes = []

    def get(self, request):
        try:
            with connection.cursor() as cursor:
                cursor.execute("SELECT 1")
        except Exception:
            logger.exception("Health check: database unavailable")
            return Response({"status": "error", "database": False}, status=status.HTTP_503_SERVICE_UNAVAILABLE)
        return Response({"status": "ok", "database": True})


class SupportInfoView(APIView):
    """Public support contact details shown on the Contact page."""

    permission_classes = [AllowAny]
    authentication_classes = []

    def get(self, request):
        return Response({"email": settings.SUPPORT_EMAIL, "phone": settings.SUPPORT_PHONE})


class ContactCreateView(generics.CreateAPIView):
    permission_classes = [AllowAny]
    throttle_classes = [ContactThrottle]
    serializer_class = ContactMessageCreateSerializer

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        thanks = "Thank you, we have received your message and will reply by email."
        if serializer.validated_data.pop("website", ""):
            return Response({"detail": thanks}, status=status.HTTP_201_CREATED)  # honeypot: store nothing
        user = request.user if request.user and request.user.is_authenticated else None
        msg = serializer.save(user=user, ip_address=request.META.get("REMOTE_ADDR") or None)
        self.notify(msg)
        return Response({"id": msg.id, "detail": thanks}, status=status.HTTP_201_CREATED)

    @staticmethod
    def notify(msg):
        """Email the support inbox; never fails the visitor's request."""
        if not settings.SUPPORT_EMAIL:
            return
        lines = [
            f"Topic: {msg.get_topic_display()}",
            f"From: {msg.name} <{msg.email}>" + (f", phone {msg.phone}" if msg.phone else ""),
        ]
        if msg.place_slug:
            lines.append(f"Place: {settings.FRONTEND_URL}/museums/{msg.place_slug}")
        if msg.booking_reference:
            lines.append(f"Booking: {msg.booking_reference}")
        lines += ["", msg.message]
        try:
            send_mail(
                f"[Contact #{msg.id}] {msg.get_topic_display()} - {msg.name}",
                "\n".join(lines),
                settings.DEFAULT_FROM_EMAIL,
                [settings.SUPPORT_EMAIL],
                fail_silently=True,
            )
        except Exception:
            logger.exception("Could not email contact message %s", msg.id)


class AdminSupportMessageViewSet(
    mixins.ListModelMixin, mixins.RetrieveModelMixin, mixins.UpdateModelMixin, viewsets.GenericViewSet
):
    """Admin panel inbox: list messages and change their status / internal note."""

    permission_classes = [IsPanelUser]
    serializer_class = AdminContactMessageSerializer
    queryset = ContactMessage.objects.select_related("user")
    filterset_fields = ("status", "topic")
    search_fields = ("name", "email", "phone", "message", "place_slug", "booking_reference")
    ordering_fields = ("created_at", "status")
    http_method_names = ["get", "patch", "head", "options"]
