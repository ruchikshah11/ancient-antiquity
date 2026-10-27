import csv

from django.db import transaction
from django.db.models import Count, Q, Sum
from django.http import HttpResponse
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import mixins, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.pagination import PageNumberPagination
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from accounts.models import User
from accounts.permissions import IsAdminRole, IsApprovedAgent, IsKioskDevice, IsPanelUser
from bookings import services as booking_services
from bookings.models import Booking
from bookings.serializers import BookingCreateSerializer, BookingSerializer, GroupBookingSerializer
from museums.models import Museum

from . import services
from .models import AgentProfile, KioskDevice, PartnerAccount, Settlement
from .serializers import (
    AgentAdminUpdateSerializer, AgentApplySerializer, AgentBookingSerializer, AgentPaymentSerializer,
    AgentProfileSerializer, KioskBookingSerializer, KioskCreateSerializer, KioskSerializer, KioskUpdateSerializer,
    PartnerAccountSerializer, SettlementGenerateSerializer, SettlementSerializer, StatementBookingSerializer,
)


# --------------------------------------------------------------------------------------- tour operators

class AgentMeView(APIView):
    """The signed-in user's tour operator profile (404 if they never applied) plus dashboard figures."""

    permission_classes = [IsAuthenticated]

    def get(self, request):
        profile = AgentProfile.objects.filter(user=request.user).first()
        if not profile:
            return Response({"profile": None, "dashboard": None})
        services.recalc_balance(profile)
        return Response({
            "profile": AgentProfileSerializer(profile).data,
            "dashboard": services.agent_dashboard(profile) if profile.is_approved else None,
        })


class AgentApplyView(APIView):
    """A signed-in visitor applies to become a tour operator partner (pending until an admin approves)."""

    permission_classes = [IsAuthenticated]

    def post(self, request):
        user = request.user
        if user.role != User.Role.VISITOR and not hasattr(user, "agent_profile"):
            raise ValidationError("Only visitor accounts can apply. Please use a separate account for your agency.")
        profile = AgentProfile.objects.filter(user=user).first()
        if profile and profile.status in (AgentProfile.Status.APPROVED, AgentProfile.Status.SUSPENDED):
            raise ValidationError("Your agency already has a partner account.")
        # A pending applicant may correct their details; a rejected one may apply again.
        serializer = AgentApplySerializer(profile, data=request.data)
        serializer.is_valid(raise_exception=True)
        profile = serializer.save(user=user, status=AgentProfile.Status.PENDING, is_approved=False)
        return Response(AgentProfileSerializer(profile).data, status=status.HTTP_201_CREATED)


def agent_profile(request):
    return AgentProfile.objects.get(user=request.user)


class AgentBookingsView(APIView):
    """GET: the agent's bookings (paginated, ?status=, ?search=). POST: book on account (individual or group)."""

    permission_classes = [IsApprovedAgent]

    def get(self, request):
        booking_services.expire_stale_bookings()
        qs = (
            Booking.objects.filter(agent=request.user)
            .select_related("museum__city__state", "slot", "user").prefetch_related("items")
            .order_by("-created_at")
        )
        st = request.query_params.get("status")
        if st:
            qs = qs.filter(status=st)
        q = (request.query_params.get("search") or "").strip()
        if q:
            qs = qs.filter(Q(reference__icontains=q) | Q(visitor_name__icontains=q)
                           | Q(organisation_name__icontains=q) | Q(museum__name__icontains=q))
        upcoming = request.query_params.get("upcoming")
        if upcoming:
            qs = qs.filter(visit_date__gte=timezone.localdate())
        paginator = PageNumberPagination()
        page = paginator.paginate_queryset(qs, request, view=self)
        return paginator.get_paginated_response(AgentBookingSerializer(page, many=True).data)

    def post(self, request):
        profile = agent_profile(request)
        data = request.data.copy() if hasattr(request.data, "copy") else dict(request.data)
        # The agency's contact details are used when the booking has none of its own.
        if not data.get("visitor_email"):
            data["visitor_email"] = request.user.email
        if not data.get("visitor_phone"):
            data["visitor_phone"] = profile.contact_phone
        serializer_class = GroupBookingSerializer if data.get("group_type") else BookingCreateSerializer
        serializer = serializer_class(data=data)
        serializer.is_valid(raise_exception=True)
        booking = services.create_agent_booking(profile=profile, data=serializer.validated_data)
        return Response(AgentBookingSerializer(booking).data, status=status.HTTP_201_CREATED)


class AgentBookingCancelView(APIView):
    permission_classes = [IsApprovedAgent]

    def post(self, request, reference):
        booking = get_object_or_404(Booking, reference=reference.upper(), agent=request.user)
        booking = services.cancel_agent_booking(booking, agent_profile(request))
        return Response(AgentBookingSerializer(booking).data)


class AgentStatementView(APIView):
    permission_classes = [IsApprovedAgent]

    def get(self, request):
        profile = services.recalc_balance(agent_profile(request))
        month = request.query_params.get("month") or f"{timezone.localdate():%Y-%m}"
        return Response(statement_payload(profile, month))


def statement_payload(profile, month):
    st = services.agent_statement(profile, month)
    st["bookings"] = StatementBookingSerializer(st["bookings"], many=True).data
    st["payments"] = AgentPaymentSerializer(st["payments"], many=True).data
    return st


class AdminAgentViewSet(mixins.ListModelMixin, mixins.RetrieveModelMixin, mixins.UpdateModelMixin,
                        viewsets.GenericViewSet):
    """Admin: tour operator applications and accounts. ?status=pending|approved|rejected|suspended, ?search="""

    permission_classes = [IsAdminRole]
    queryset = AgentProfile.objects.select_related("user", "approved_by")
    filterset_fields = ["status"]
    search_fields = ["company_name", "user__email", "gstin", "contact_phone", "city"]

    def get_serializer_class(self):
        if self.action in ("update", "partial_update"):
            return AgentAdminUpdateSerializer
        return AgentProfileSerializer

    def update(self, request, *args, **kwargs):
        super().update(request, *args, **kwargs)
        return Response(AgentProfileSerializer(self.get_object()).data)

    @action(detail=True, methods=["post"])
    def approve(self, request, pk=None):
        profile = self.get_object()
        user = profile.user
        if user.role not in (User.Role.VISITOR, User.Role.AGENT):
            raise ValidationError("Only visitor accounts can become tour operators.")
        with transaction.atomic():
            for field in ("commission_percent", "credit_limit"):
                if field in request.data:
                    s = AgentAdminUpdateSerializer(profile, data={field: request.data[field]}, partial=True)
                    s.is_valid(raise_exception=True)
                    s.save()
            profile.refresh_from_db()
            profile.status = AgentProfile.Status.APPROVED
            profile.is_approved = True
            profile.approved_by = request.user
            profile.approved_at = timezone.now()
            profile.save()
            user.role = User.Role.AGENT
            user.save(update_fields=["role"])
        return Response(AgentProfileSerializer(profile).data)

    @action(detail=True, methods=["post"])
    def reject(self, request, pk=None):
        """Reject an application, or suspend an approved agent (they keep their history and balance)."""
        profile = self.get_object()
        with transaction.atomic():
            new = AgentProfile.Status.SUSPENDED if profile.is_approved else AgentProfile.Status.REJECTED
            profile.status = new
            profile.is_approved = False
            profile.admin_note = (request.data.get("reason") or profile.admin_note or "")[:255]
            profile.save()
            if profile.user.role == User.Role.AGENT:
                profile.user.role = User.Role.VISITOR
                profile.user.save(update_fields=["role"])
        return Response(AgentProfileSerializer(profile).data)

    @action(detail=True, methods=["get", "post"])
    def payments(self, request, pk=None):
        profile = self.get_object()
        if request.method == "GET":
            return Response(AgentPaymentSerializer(profile.payments.select_related("recorded_by"), many=True).data)
        serializer = AgentPaymentSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        payment = services.record_agent_payment(profile=profile, by=request.user, **serializer.validated_data)
        profile.refresh_from_db()
        return Response(
            {"payment": AgentPaymentSerializer(payment).data, "agent": AgentProfileSerializer(profile).data},
            status=status.HTTP_201_CREATED,
        )

    @action(detail=True, methods=["get"])
    def statement(self, request, pk=None):
        profile = services.recalc_balance(self.get_object())
        month = request.query_params.get("month") or f"{timezone.localdate():%Y-%m}"
        return Response(statement_payload(profile, month))


# --------------------------------------------------------------------------------------- settlements

def settlements_for(user):
    qs = Settlement.objects.select_related("museum__city", "approved_by", "created_by")
    if user.is_admin_role:
        return qs
    return qs.filter(museum__in=Museum.for_panel_user(user))


def filter_settlements(request, qs):
    p = request.query_params
    if p.get("status"):
        qs = qs.filter(status=p["status"])
    if p.get("museum"):
        qs = qs.filter(museum__slug=p["museum"])
    if p.get("from"):
        qs = qs.filter(period_end__gte=p["from"])
    if p.get("to"):
        qs = qs.filter(period_start__lte=p["to"])
    return qs


class SettlementViewSet(mixins.ListModelMixin, mixins.RetrieveModelMixin, viewsets.GenericViewSet):
    """Partner view: staff see their places' settlements (read-only); admins see all."""

    permission_classes = [IsPanelUser]
    serializer_class = SettlementSerializer

    def get_queryset(self):
        return filter_settlements(self.request, settlements_for(self.request.user))

    def retrieve(self, request, *args, **kwargs):
        settlement = self.get_object()
        data = SettlementSerializer(settlement).data
        bookings = services.settlement_bookings(settlement.museum, settlement.period_start, settlement.period_end)
        data["by_channel"] = [
            {"channel": r["channel"], "bookings": r["n"], "amount": services.money((r["a"] or 0) + (r["v"] or 0))}
            for r in bookings.order_by().values("channel").annotate(
                n=Count("id"), a=Sum("total_amount"),
                v=Sum("voucher_amount"),
            ).order_by("channel")
        ]
        data["bookings"] = [
            {"reference": b.reference, "paid_at": b.paid_at, "channel": b.channel, "visitors": b.total_visitors,
             "amount": services.money(b.total_amount + b.voucher_amount)}
            for b in bookings.order_by("paid_at")[:500]
        ]
        data["late_refunds"] = [
            {"reference": b.reference, "cancelled_at": b.cancelled_at, "amount": b.refund_amount}
            for b in services.late_refunds(settlement.museum, settlement.period_start, settlement.period_end)[:200]
        ]
        account = PartnerAccount.objects.filter(museum=settlement.museum).first()
        data["payout_account"] = PartnerAccountSerializer(account).data if account else None
        return Response(data)


class AdminSettlementViewSet(mixins.DestroyModelMixin, viewsets.GenericViewSet):
    permission_classes = [IsAdminRole]
    serializer_class = SettlementSerializer

    def get_queryset(self):
        return settlements_for(self.request.user)

    @action(detail=False, methods=["post"])
    def generate(self, request):
        serializer = SettlementGenerateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        d = serializer.validated_data
        museum = d.get("museum")
        created, updated, skipped = services.generate_settlements(
            start=d["start"], end=d["to"], by=request.user,
            museums=Museum.objects.filter(pk=museum.pk) if museum else None,
        )
        return Response({
            "created": SettlementSerializer(created, many=True).data,
            "updated": SettlementSerializer(updated, many=True).data,
            "skipped": skipped,
        }, status=status.HTTP_201_CREATED)

    def destroy(self, request, *args, **kwargs):
        if self.get_object().status != Settlement.Status.DRAFT:
            raise ValidationError("Only draft settlements can be deleted.")
        return super().destroy(request, *args, **kwargs)

    @action(detail=True, methods=["post"])
    def approve(self, request, pk=None):
        s = self.get_object()
        if s.status != Settlement.Status.DRAFT:
            raise ValidationError("Only draft settlements can be approved.")
        s.status = Settlement.Status.APPROVED
        s.approved_by = request.user
        s.approved_at = timezone.now()
        s.save()
        return Response(SettlementSerializer(s).data)

    @action(detail=True, methods=["post"], url_path="mark-paid")
    def mark_paid(self, request, pk=None):
        s = self.get_object()
        if s.status != Settlement.Status.APPROVED:
            raise ValidationError("Approve the settlement before marking it paid.")
        reference = (request.data.get("reference") or "").strip()
        if not reference:
            raise ValidationError({"reference": "Enter the bank transfer / UTR reference."})
        s.status = Settlement.Status.PAID
        s.paid_reference = reference[:80]
        s.paid_at = timezone.now()
        s.save()
        return Response(SettlementSerializer(s).data)


CSV_COLUMNS = [
    ("Place", "museum_name"), ("City", "city_name"), ("From", "period_start"), ("To", "period_end"),
    ("Bookings", "booking_count"), ("Visitors", "visitor_count"), ("Online", "gross_online"),
    ("Kiosk", "gross_kiosk"), ("Counter", "gross_counter"), ("Tour operators", "gross_agent"),
    ("Gross", "gross_total"), ("Refunds", "refunds"), ("Fee %", "platform_fee_percent"),
    ("Platform fee", "platform_fee"), ("GST on fee", "gst_on_fee"), ("Net payable", "net_payable"),
    ("Status", "status_label"), ("Paid reference", "paid_reference"), ("Paid at", "paid_at"),
]


class SettlementsCsvView(APIView):
    permission_classes = [IsPanelUser]

    def get(self, request):
        qs = filter_settlements(request, settlements_for(request.user))
        response = HttpResponse(content_type="text/csv; charset=utf-8")
        response["Content-Disposition"] = f'attachment; filename="settlements-{timezone.localdate()}.csv"'
        response.write("﻿")  # Excel opens UTF-8 correctly with a BOM
        writer = csv.writer(response)
        writer.writerow([c[0] for c in CSV_COLUMNS])
        for row in SettlementSerializer(qs, many=True).data:
            writer.writerow([row[c[1]] if row[c[1]] is not None else "" for c in CSV_COLUMNS])
        return response


class AdminPartnerAccountViewSet(viewsets.ModelViewSet):
    permission_classes = [IsAdminRole]
    serializer_class = PartnerAccountSerializer
    queryset = PartnerAccount.objects.select_related("museum").order_by("museum__name")
    search_fields = ["museum__name", "bank_name", "razorpay_account_id"]


# --------------------------------------------------------------------------------------- kiosks

class AdminKioskViewSet(mixins.ListModelMixin, mixins.CreateModelMixin, mixins.RetrieveModelMixin,
                        mixins.UpdateModelMixin, viewsets.GenericViewSet):
    """Admin: kiosk devices. Creating one creates its sign-in account (role kiosk). Disable instead of deleting."""

    permission_classes = [IsAdminRole]
    queryset = KioskDevice.objects.select_related("user").prefetch_related("museums")

    def get_serializer_class(self):
        if self.action == "create":
            return KioskCreateSerializer
        if self.action in ("update", "partial_update"):
            return KioskUpdateSerializer
        return KioskSerializer

    def perform_create(self, serializer):
        serializer.save(created_by=self.request.user)


def kiosk_device(request):
    return request.user.kiosk_device


def kiosk_museum(request, slug):
    museum = Museum.objects.filter(slug=slug or "", is_active=True).first()
    if not museum:
        raise ValidationError({"museum": "Unknown place."})
    if not kiosk_device(request).museums.filter(pk=museum.pk).exists():
        raise PermissionDenied("This kiosk is not set up for that place.")
    return museum


class KioskMeView(APIView):
    permission_classes = [IsKioskDevice]

    def get(self, request):
        device = kiosk_device(request)
        return Response({
            "id": device.id,
            "name": device.name,
            "museums": [
                {"slug": m.slug, "name": m.name, "city_name": m.city.name, "image_url": m.image_url}
                for m in device.museums.filter(is_active=True).select_related("city").order_by("name")
            ],
        })


class KioskSessionView(APIView):
    """Today's sale screen for one place: ticket prices for today and slots a walk-in can still join."""

    permission_classes = [IsKioskDevice]

    def get(self, request):
        museum = kiosk_museum(request, request.query_params.get("museum"))
        today = timezone.localdate()
        now = timezone.localtime().time()
        closure = museum.closure_on(today)
        weekly_closed = museum.is_closed_on(today)
        booked = booking_services.booked_visitors_by_slot(museum, today)
        slots = []
        for slot in museum.slots.filter(is_active=True).order_by("start_time"):
            if slot.end_time <= now:
                continue  # over
            available = max(slot.capacity - booked.get(slot.id, 0), 0)
            closed = closure["slots"].get(slot.id)
            slots.append({
                "id": slot.id, "start_time": slot.start_time, "end_time": slot.end_time,
                "running": slot.start_time <= now, "available": available,
                "bookable": available > 0 and not closed and not closure["closed"] and not weekly_closed,
                "closed_reason": closed or "",
            })
        return Response({
            "museum": {"slug": museum.slug, "name": museum.name, "city_name": museum.city.name,
                       "image_url": museum.image_url},
            "date": today,
            "closed": bool(closure["closed"] or weekly_closed),
            "closed_reason": closure.get("reason") or ("Weekly closed day" if weekly_closed else ""),
            "tickets": booking_services.prices_for(museum, today),
            "slots": slots,
        })


class KioskBookingView(APIView):
    """Create a pending walk-in booking; pay it via /api/bookings/<ref>/payment-order/ and /pay/."""

    permission_classes = [IsKioskDevice]

    def post(self, request):
        # Check the place first: a kiosk must never learn about (or sell) another place's slots.
        kiosk_museum(request, request.data.get("museum"))
        serializer = KioskBookingSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        booking = booking_services.create_booking(user=request.user, channel=Booking.Channel.KIOSK, **data)
        return Response(BookingSerializer(booking).data, status=status.HTTP_201_CREATED)
