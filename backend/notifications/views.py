from datetime import timedelta

from django.conf import settings
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import permissions, status
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.response import Response
from rest_framework.views import APIView

from bookings.models import Booking
from museums.models import Museum

from . import services
from .models import NotificationLog, PushSubscription

RESEND_LIMIT_PER_HOUR = 3


class ResendConfirmationView(APIView):
    """Email the ticket again (visitor lost the mail, or staff resending for a visitor)."""

    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, reference):
        booking = get_object_or_404(Booking.objects.select_related("museum", "slot"), reference=reference)
        user = request.user
        own = booking.user_id == user.id
        # Staff may resend only for places they are assigned to; admins for any place.
        staff_ok = user.is_panel_user and Museum.for_panel_user(user).filter(pk=booking.museum_id).exists()
        if not (own or staff_ok):
            raise PermissionDenied("You can only resend your own tickets.")
        if booking.status not in (Booking.Status.CONFIRMED, Booking.Status.CHECKED_IN):
            raise ValidationError("Only confirmed bookings have a ticket to send.")
        if not booking.visitor_email:
            raise ValidationError("This booking has no email address.")
        # Count every attempt (sent or failed) so the endpoint cannot be used to spam an inbox.
        recent = NotificationLog.objects.filter(
            booking=booking, kind=services.KIND_RESEND, channel=NotificationLog.Channel.EMAIL,
            created_at__gte=timezone.now() - timedelta(hours=1),
        ).count()
        if recent >= RESEND_LIMIT_PER_HOUR:
            return Response(
                {"detail": "This ticket was already emailed several times in the last hour. Please try again later."},
                status=status.HTTP_429_TOO_MANY_REQUESTS,
            )
        log = services.send_booking_email(booking, services.KIND_RESEND, user=request.user)
        if log.status != NotificationLog.Status.SENT:
            return Response({"detail": "The email could not be sent right now. Please try again later."},
                            status=status.HTTP_502_BAD_GATEWAY)
        return Response({"detail": f"Ticket emailed to {booking.visitor_email}."})


class PushPublicKeyView(APIView):
    """VAPID public key the browser needs for PushManager.subscribe(); null when push is not configured."""

    permission_classes = [permissions.AllowAny]

    def get(self, request):
        return Response({"public_key": settings.VAPID_PUBLIC_KEY if services.push_configured() else None})


class PushSubscribeView(APIView):
    """Save (or move to this user) a browser push subscription: the JSON of PushSubscription.toJSON()."""

    permission_classes = [permissions.IsAuthenticated]

    def post(self, request):
        if not services.push_configured():
            raise ValidationError("Push notifications are not configured on this server.")
        data = request.data
        keys = data.get("keys") or {}
        endpoint = str(data.get("endpoint") or "")
        p256dh, auth = str(keys.get("p256dh") or ""), str(keys.get("auth") or "")
        if not endpoint.startswith("https://") or len(endpoint) > 1000 or not p256dh or not auth:
            raise ValidationError("A push subscription needs an https endpoint and p256dh/auth keys.")
        if len(p256dh) > 200 or len(auth) > 100:
            raise ValidationError("Invalid push subscription keys.")
        sub, created = PushSubscription.objects.update_or_create(
            endpoint=endpoint,
            defaults={"user": request.user, "p256dh": p256dh, "auth": auth,
                      "user_agent": request.META.get("HTTP_USER_AGENT", "")[:300]},
        )
        return Response({"subscribed": True}, status=status.HTTP_201_CREATED if created else status.HTTP_200_OK)


class PushUnsubscribeView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request):
        endpoint = str(request.data.get("endpoint") or "")
        qs = PushSubscription.objects.filter(user=request.user)
        if endpoint:
            qs = qs.filter(endpoint=endpoint)
        deleted, _ = qs.delete()
        return Response({"subscribed": False, "removed": deleted})
