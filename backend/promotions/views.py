from django.db.models import Q
from django.shortcuts import get_object_or_404
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from accounts.permissions import IsAdminRole, IsPanelUser
from bookings.models import Booking
from bookings.serializers import BookingSerializer

from . import services
from .models import GiftVoucher, PromoCode
from .serializers import ApplyCodeSerializer, GiftVoucherSerializer, PromoCodeSerializer, RemoveCodeSerializer


def _own_booking(request, reference):
    return get_object_or_404(Booking, reference=reference, user=request.user)


def _booking_data(booking):
    booking = Booking.objects.select_related("museum__city__state", "slot", "user").prefetch_related(
        "items"
    ).get(pk=booking.pk)
    return BookingSerializer(booking).data


class ApplyCodeView(APIView):
    """POST {code}: apply a promo code or gift voucher to the visitor's own pending booking."""

    permission_classes = [IsAuthenticated]

    def post(self, request, reference):
        services.release_stale_vouchers()
        booking = _own_booking(request, reference)
        serializer = ApplyCodeSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        booking = services.apply_code(booking, serializer.validated_data["code"])
        return Response(_booking_data(booking))


class RemoveCodeView(APIView):
    """POST {kind?: promo|voucher}: take the code(s) off again while the booking is unpaid."""

    permission_classes = [IsAuthenticated]

    def post(self, request, reference):
        booking = _own_booking(request, reference)
        serializer = RemoveCodeSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        booking = services.remove_code(booking, serializer.validated_data.get("kind") or None)
        return Response(_booking_data(booking))


class PromoCodeViewSet(viewsets.ModelViewSet):
    permission_classes = [IsAdminRole]
    serializer_class = PromoCodeSerializer
    search_fields = ["code", "description"]
    filterset_fields = ["is_active", "discount_type", "scope"]

    def get_queryset(self):
        return PromoCode.objects.select_related("created_by").prefetch_related("museums")

    def list(self, request, *args, **kwargs):
        services.booking_services.expire_stale_bookings()
        return super().list(request, *args, **kwargs)

    def perform_create(self, serializer):
        serializer.save(created_by=self.request.user)

    def destroy(self, request, *args, **kwargs):
        promo = self.get_object()
        if promo.redemptions.exists():
            raise ValidationError("This code has been used; deactivate it instead of deleting.")
        return super().destroy(request, *args, **kwargs)


class GiftVoucherViewSet(viewsets.ModelViewSet):
    """Admins manage vouchers; counter staff may list, issue and look up balances."""

    serializer_class = GiftVoucherSerializer
    search_fields = ["code", "recipient_name", "recipient_email", "purchaser_name", "purchaser_email"]
    filterset_fields = ["is_active"]

    def get_permissions(self):
        if self.action in ("list", "retrieve", "create", "lookup"):
            return [IsPanelUser()]
        return [IsAdminRole()]

    def get_queryset(self):
        return GiftVoucher.objects.select_related("issued_by").prefetch_related("redemptions__booking")

    def list(self, request, *args, **kwargs):
        services.release_stale_vouchers()
        return super().list(request, *args, **kwargs)

    def perform_create(self, serializer):
        send = serializer.validated_data.get("send_email", False)
        voucher = serializer.save(issued_by=self.request.user)
        if send:
            services.email_voucher(voucher)

    def destroy(self, request, *args, **kwargs):
        voucher = self.get_object()
        if voucher.redemptions.exists():
            raise ValidationError("This voucher has been used; deactivate it instead of deleting.")
        return super().destroy(request, *args, **kwargs)

    @action(detail=True, methods=["post"])
    def deactivate(self, request, pk=None):
        voucher = self.get_object()
        voucher.is_active = False
        voucher.save(update_fields=["is_active"])
        return Response(self.get_serializer(voucher).data)

    @action(detail=True, methods=["post"], url_path="send-email")
    def send_email(self, request, pk=None):
        voucher = self.get_object()
        if not voucher.recipient_email:
            raise ValidationError("This voucher has no recipient email.")
        return Response({"sent": services.email_voucher(voucher)})

    @action(detail=False, methods=["get"])
    def lookup(self, request):
        """Balance check at the counter: ?code=GV-XXXX-XXXX."""
        services.release_stale_vouchers()
        code = services.normalize(request.query_params.get("code"))
        voucher = GiftVoucher.objects.filter(Q(code=code)).first() if code else None
        if not voucher:
            return Response({"detail": "No gift voucher with this code."}, status=status.HTTP_404_NOT_FOUND)
        return Response(self.get_serializer(voucher).data)
