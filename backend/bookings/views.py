import datetime
import re

from django.conf import settings

from django.contrib.auth import get_user_model
from django.db import transaction
from django.db.models import Count, Q, Sum
from django.utils import timezone
from django.utils.dateparse import parse_date
from rest_framework import mixins, serializers, status, viewsets
from rest_framework.permissions import AllowAny
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.response import Response
from rest_framework.views import APIView
from django_filters.rest_framework import DjangoFilterBackend
from rest_framework.filters import OrderingFilter, SearchFilter

from accounts.permissions import IsAdminRole, IsPanelUser
from museums.models import Gate, Museum

from . import services
from .models import Booking
from . import payments
from .models import GateScan
from .serializers import (
    RazorpayPaySerializer,
    BookingAddOnsSerializer,
    BookingCreateSerializer,
    GroupBookingSerializer,
    BookingSerializer,
    CheckinSyncSerializer,
    CounterSaleSerializer,
    PaySerializer,
)

PAID = [Booking.Status.CONFIRMED, Booking.Status.CHECKED_IN]
NOT_ASSIGNED = "You are not assigned to this museum."


def panel_bookings(user):
    """Bookings a panel user may see: admins all, staff only those at their assigned places.

    Raises PermissionDenied for staff with no assigned place, so the panel can say why it is empty.
    """
    if user.is_admin_role:
        return Booking.objects.all()
    museums = Museum.for_panel_user(user)
    if not museums.exists():
        raise PermissionDenied(f"{NOT_ASSIGNED} Ask an administrator to assign you to a place.")
    return Booking.objects.filter(museum__in=museums)


def ensure_museum_access(user, museum):
    if not user.is_admin_role and not museum.staff.filter(pk=user.pk).exists():
        raise PermissionDenied(NOT_ASSIGNED)


def _fts_phrase(word):
    return '"' + word.replace('"', '""') + '"'


def _fts_ids(match):
    """Booking ids matching an FTS5 query on the booking_search table (SQLite, see migration 0014)."""
    from django.db.models.expressions import RawSQL

    return RawSQL("SELECT rowid FROM booking_search WHERE booking_search MATCH %s", (match,))


def search_bookings(queryset, term):
    """Filter bookings by what was typed in the admin search box, picking the fastest match (lakhs of bookings):

    - a booking reference (AA-XXXXXXXX, or 6+ capital letters/digits) -> reference prefix (unique index)
    - an email -> visitor email prefix
    - a phone number (6+ digits) -> the last 10 digits (partial numbers: how the number starts or ends)
    - anything else -> words of the visitor name, organisation or place name (each word as a prefix)

    SQLite uses the FTS5 table booking_search; PostgreSQL the pg_trgm indexes (both from migration 0014).
    """
    from django.db import connection

    term = (term or "").strip()
    if not term:
        return queryset
    fts = connection.vendor == "sqlite"
    upper = term.upper()
    digits = "".join(ch for ch in term if ch.isdigit())
    if upper.startswith("AA-") or (len(term) >= 6 and term.isalnum() and not term.isdigit() and term.upper() == term):
        ref = upper if upper.startswith("AA-") else f"AA-{upper}"
        # References are upper case: an index range instead of LIKE (case-insensitive on SQLite: full scan).
        return queryset.filter(reference__gte=ref, reference__lt=ref[:-1] + chr(ord(ref[-1]) + 1))
    if "@" in term:
        qs = queryset.filter(visitor_email__istartswith=term)
        words = [w for w in re.split(r"[^\w]+", term) if w]
        if fts and words:  # FTS narrows to a few rows; istartswith above keeps the exact meaning
            qs = qs.filter(id__in=_fts_ids(f"email : {_fts_phrase(' '.join(words))}*"))
        return qs
    if len(digits) >= 6 and len(digits) >= len(term.replace(" ", "").replace("+", "")) - 1:
        last10 = digits[-10:]
        if fts:
            if len(digits) >= 10:
                return queryset.filter(id__in=_fts_ids(f'phone : "{last10}"'))
            return queryset.filter(id__in=_fts_ids(f'phone : "{digits}"* OR tail : "{digits}"'))
        if len(digits) >= 10:
            return queryset.filter(visitor_phone__endswith=last10)
        return queryset.filter(Q(visitor_phone__endswith=digits) | Q(visitor_phone__startswith=digits))
    if fts:
        words = [w for w in term.split() if any(ch.isalnum() for ch in w)]
        if words:
            match = "{name org place} : (" + " ".join(f"{_fts_phrase(w)}*" for w in words) + ")"
            return queryset.filter(id__in=_fts_ids(match))
    return queryset.filter(
        Q(visitor_name__icontains=term) | Q(organisation_name__icontains=term) | Q(museum__name__icontains=term)
    )


class BookingSearchFilter(SearchFilter):
    """?search= through search_bookings() (fast per kind of term instead of icontains on every column)."""

    def filter_queryset(self, request, queryset, view):
        return search_bookings(queryset, request.query_params.get(self.search_param))


class BookingViewSet(
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    mixins.CreateModelMixin,
    viewsets.GenericViewSet,
):
    """Visitors see their own bookings; staff/admin see all (unless ?mine=1)."""

    lookup_field = "reference"
    filterset_fields = {
        "status": ["exact"], "channel": ["exact"], "is_group": ["exact"],
        "visit_date": ["exact", "gte", "lte"], "museum__slug": ["exact"],
    }
    search_fields = ["reference", "visitor_name", "visitor_email", "visitor_phone", "organisation_name", "museum__name"]
    ordering_fields = ["created_at", "visit_date", "total_amount"]
    filter_backends = [DjangoFilterBackend, BookingSearchFilter, OrderingFilter]

    def get_queryset(self):
        services.expire_stale_bookings()
        qs = Booking.objects.select_related(
            "museum__city__state", "slot", "event_session__event", "user", "membership"
        ).prefetch_related("items", "addons")
        user = self.request.user
        if not user.is_panel_user or self.request.query_params.get("mine"):
            qs = qs.filter(user=user)
        elif not user.is_admin_role:
            # Staff: bookings at their assigned places, plus any they made for themselves.
            museums = Museum.for_panel_user(user)
            if self.action == "list" and not museums.exists():
                raise PermissionDenied(f"{NOT_ASSIGNED} Ask an administrator to assign you to a place.")
            qs = qs.filter(Q(museum__in=museums) | Q(user=user))
        return qs

    def get_serializer_class(self):
        return BookingCreateSerializer if self.action == "create" else BookingSerializer

    def create(self, request, *args, **kwargs):
        serializer = BookingCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        booking = services.create_booking(user=request.user, **serializer.validated_data)
        return Response(BookingSerializer(booking).data, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=["post"], url_path="payment-order")
    def payment_order(self, request, reference=None):
        """Start paying: returns what the browser needs to open Razorpay Checkout (or 'mock' in demo mode)."""
        booking = self.get_object()
        if booking.status != Booking.Status.PENDING:
            raise ValidationError(f"Booking is {booking.get_status_display().lower()}, nothing to pay.")
        if booking.is_hold_expired:
            raise ValidationError("Your seat hold expired. Please book again.")
        if payments.provider() == payments.MOCK:
            return Response({"provider": payments.MOCK})
        try:
            order = payments.create_order(booking)
        except Exception:
            raise ValidationError("The payment gateway is not reachable right now. Please try again in a minute.")
        return Response({
            "provider": payments.RAZORPAY,
            "test_mode": payments.is_test_mode(),
            "key_id": settings.RAZORPAY_KEY_ID,
            "order_id": order["id"],
            "amount": order["amount"],
            "currency": order["currency"],
            "name": "Ancient Antiquity",
            "description": f"{booking.museum.name} · {booking.visit_date:%d %b %Y}",
            "prefill": {"name": booking.visitor_name, "email": booking.visitor_email, "contact": booking.visitor_phone},
        })

    @action(detail=True, methods=["post"])
    def pay(self, request, reference=None):
        booking = self.get_object()
        if payments.provider() == payments.RAZORPAY:
            serializer = RazorpayPaySerializer(data=request.data)
            serializer.is_valid(raise_exception=True)
            data = serializer.validated_data
            if not booking.gateway_order_id or data["razorpay_order_id"] != booking.gateway_order_id:
                raise ValidationError("This payment does not belong to this booking.")
            if not payments.verify_checkout_signature(
                data["razorpay_order_id"], data["razorpay_payment_id"], data["razorpay_signature"]
            ):
                raise ValidationError("Payment could not be verified. If money was deducted it will be refunded automatically.")
            booking = services.finalize_gateway_payment(
                booking.pk, data["razorpay_payment_id"], payments.payment_method(data["razorpay_payment_id"])
            )
            return Response(BookingSerializer(booking).data)

        if booking.status != Booking.Status.PENDING:
            raise ValidationError(f"Booking is {booking.get_status_display().lower()}, nothing to pay.")
        serializer = PaySerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        services.confirm_payment(booking, serializer.validated_data["method"])
        return Response(BookingSerializer(booking).data)

    @action(detail=True, methods=["post"])
    def addons(self, request, reference=None):
        """Replace the add-ons of the visitor's own pending booking: {"items": [{"addon": id, "quantity": n}]}."""
        booking = self.get_object()
        if booking.user_id != request.user.id:
            raise PermissionDenied("Only the visitor who made this booking can change its add-ons.")
        serializer = BookingAddOnsSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        booking = services.set_booking_addons(booking, serializer.validated_data["items"])
        return Response(BookingSerializer(self.get_queryset().get(pk=booking.pk)).data)

    @action(detail=True, methods=["post"])
    def cancel(self, request, reference=None):
        booking = self.get_object()
        if not booking.can_cancel:
            raise ValidationError("This booking can no longer be cancelled.")
        try:
            booking = services.cancel_booking(booking)
        except Exception as exc:  # gateway refused the refund: keep the booking as it was
            if isinstance(exc, ValidationError):
                raise
            raise ValidationError("The refund could not be started right now, so the booking was not cancelled. Please try again.")
        return Response(BookingSerializer(booking).data)

    @action(detail=False, methods=["post"])
    def group(self, request):
        """Group booking (21-60): discounted, optional free escorts, one ticket/QR for the whole group."""
        serializer = GroupBookingSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        booking = services.create_booking(user=request.user, **serializer.validated_data)
        return Response(BookingSerializer(booking).data, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=["get"])
    def invoice(self, request, reference=None):
        """GST tax invoice for a paid booking (owner, or a panel user who can see the booking)."""
        from .reports import build_invoice

        booking = self.get_object()
        if booking.status not in PAID:
            raise ValidationError("An invoice is available once the booking is paid.")
        return Response(build_invoice(booking))

    @action(detail=False, methods=["post"], permission_classes=[IsPanelUser])
    def counter(self, request):
        """Walk-in sale at the ticket window: confirmed immediately, optionally checked in."""
        serializer = CounterSaleSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        ensure_museum_access(request.user, serializer.validated_data["museum"])
        booking = services.create_booking(
            user=request.user, channel=Booking.Channel.COUNTER, **serializer.validated_data
        )
        return Response(BookingSerializer(booking).data, status=status.HTTP_201_CREATED)

    @action(detail=False, methods=["get"], permission_classes=[IsPanelUser], url_path="gate-manifest")
    def gate_manifest(self, request):
        """All valid tickets (and combo passes) for one museum and day, so a gate device can verify while offline."""
        from passes import services as pass_services

        services.expire_stale_bookings()
        museum = Museum.objects.filter(slug=request.query_params.get("museum", "")).first()
        if not museum:
            raise ValidationError({"museum": "Pass ?museum=<slug>."})
        ensure_museum_access(request.user, museum)
        day = parse_date(request.query_params.get("date", "") or "") or timezone.localdate()
        bookings = (
            Booking.objects.filter(
                museum=museum, visit_date=day,
                status__in=[Booking.Status.CONFIRMED, Booking.Status.CHECKED_IN],
            )
            .select_related("slot", "event_session__event")
            .prefetch_related("items", "addons")
            .order_by("slot__start_time", "event_session__start_time", "reference")
        )
        return Response({
            "museum": museum.slug,
            "museum_name": museum.name,
            "date": day,
            "generated_at": timezone.now(),
            "gates": [{"id": g.id, "name": g.name} for g in museum.gates.filter(is_active=True)],
            "tickets": [
                {
                    "reference": b.reference,
                    "status": b.status,
                    "visitor_name": b.visitor_name,
                    "total_visitors": b.total_visitors,
                    "slot_start": b.slot_start_time,
                    "slot_end": b.slot_end_time,
                    "event_title": b.event_title,
                    "items": ", ".join(f"{i.quantity} x {i.ticket_name}" for i in b.items.all())
                    + (f", {b.escort_count} x Escort (free)" if b.escort_count else "")
                    + (f" + {b.addons_summary}" if b.addons_summary else ""),
                    "addons_summary": b.addons_summary,
                    "checked_in_at": b.checked_in_at,
                    "is_group": b.is_group,
                    "organisation_name": b.organisation_name,
                    "visitors_arrived": b.visitors_arrived,
                }
                for b in bookings
            ] + pass_services.manifest_entries(museum, day),
        })

    @action(detail=False, methods=["post"], permission_classes=[IsPanelUser], url_path="checkin-sync")
    def checkin_sync(self, request):
        """Upload check-ins recorded offline. Safe to resend: repeats of the same scan are accepted.

        Combo passes (AP- references) are admitted once per place. An optional gate id may be sent at the top
        level ("gate") or per entry; unknown gates are ignored so an offline upload never fails because of one.
        """
        serializer = CheckinSyncSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        museum = serializer.validated_data["museum"]
        ensure_museum_access(request.user, museum)
        now = timezone.now()
        raw_entries = request.data.get("entries") or []
        results = []
        for index, entry in enumerate(serializer.validated_data["entries"]):
            ref = entry["reference"].strip().upper()
            at = min(entry["checked_in_at"], now)
            raw = raw_entries[index] if index < len(raw_entries) and isinstance(raw_entries[index], dict) else {}
            gate = gate_for(museum, raw.get("gate") or request.data.get("gate"))
            if ref.startswith("AP-"):
                results.append(sync_pass_entry(museum, ref, at, entry.get("scan_id"), request.user, gate))
                continue
            with transaction.atomic():
                booking = Booking.objects.select_for_update().filter(reference=ref).first()
                scan_id = entry.get("scan_id")
                if not booking or booking.museum_id != museum.id:
                    results.append({"reference": ref, "result": "invalid", "detail": "Ticket not found for this museum."})
                elif scan_id and GateScan.objects.filter(scan_id=scan_id).exists():
                    results.append({"reference": ref, "result": "ok", "detail": ""})  # already synced earlier
                elif booking.status not in (Booking.Status.CONFIRMED, Booking.Status.CHECKED_IN):
                    results.append({
                        "reference": ref, "result": "invalid",
                        "detail": f"Booking was {booking.get_status_display().lower()} before entry.",
                    })
                elif booking.remaining_to_enter == 0:
                    same_scan = (not booking.is_group and booking.checked_in_at
                                 and abs((booking.checked_in_at - at).total_seconds()) < 2)
                    first = timezone.localtime(booking.checked_in_at).strftime("%H:%M") if booking.checked_in_at else "?"
                    results.append({
                        "reference": ref,
                        "result": "ok" if same_scan else "duplicate",
                        "detail": "" if same_scan else f"Everyone on this ticket had already entered (first at {first}).",
                    })
                else:
                    wanted = entry.get("arrived")
                    admitted = services.mark_checked_in(booking, request.user, at=at, admitted=wanted,
                                                        scan_id=scan_id, offline=True)
                    if admitted:
                        tag_scan_gate(booking, gate, scan_id)
                    over = wanted is not None and wanted > admitted
                    results.append({
                        "reference": ref,
                        "result": "duplicate" if over else "ok",
                        "detail": f"Only {admitted} of {wanted} could be admitted; the rest had already entered." if over else "",
                    })
        return Response({"results": results})

    @action(detail=False, methods=["post"], permission_classes=[IsPanelUser])
    def checkin(self, request):
        reference = (request.data.get("reference") or "").strip().upper()
        if reference.startswith("AP-"):
            return checkin_pass(request, reference)
        booking = Booking.objects.filter(reference=reference).select_related("museum", "slot", "event_session__event").first()
        if not booking:
            raise ValidationError({"reference": "No booking found with this reference."})
        ensure_museum_access(request.user, booking.museum)
        museum_slug = request.data.get("museum")
        if museum_slug and booking.museum.slug != museum_slug:
            raise ValidationError({"reference": f"This ticket is for {booking.museum.name}."})
        gate = gate_for(booking.museum, request.data.get("gate"), strict=True)
        if booking.status == Booking.Status.CHECKED_IN and booking.remaining_to_enter == 0:
            raise ValidationError({"reference": f"Already checked in at {timezone.localtime(booking.checked_in_at):%d %b %Y %H:%M}."})
        if booking.status not in (Booking.Status.CONFIRMED, Booking.Status.CHECKED_IN):
            raise ValidationError({"reference": f"Booking is {booking.get_status_display().lower()}."})
        if booking.visit_date != timezone.localdate():
            raise ValidationError({"reference": f"Ticket is valid for {booking.visit_date:%d %b %Y}, not today."})

        if booking.is_group:
            # Groups: staff count heads at the gate. Without a count, tell the UI to ask for one.
            arrived = request.data.get("arrived")
            if arrived in (None, ""):
                return Response({"needs_count": True, "booking": BookingSerializer(booking).data})
            try:
                arrived = int(arrived)
            except (TypeError, ValueError):
                raise ValidationError({"arrived": "Enter how many people are entering."})
            if not 1 <= arrived <= booking.remaining_to_enter:
                raise ValidationError({"arrived": f"Enter a number from 1 to {booking.remaining_to_enter}."})
            admitted = services.mark_checked_in(booking, request.user, admitted=arrived)
        else:
            admitted = services.mark_checked_in(booking, request.user)
        if admitted:
            tag_scan_gate(booking, gate)
        return Response(BookingSerializer(booking).data)


class PaymentConfigView(APIView):
    """Public: which gateway is active, so the checkout page can show the right payment screen."""

    permission_classes = [AllowAny]

    def get(self, request):
        live = payments.provider() == payments.RAZORPAY
        return Response({
            "provider": payments.provider(),
            "test_mode": live and payments.is_test_mode(),
            "refund_full_before_hours": settings.REFUND_FULL_BEFORE_HOURS,
        })


class RazorpayWebhookView(APIView):
    """Razorpay -> server notifications. Configure in Razorpay Dashboard -> Webhooks:
    URL https://<your-domain>/api/payments/razorpay/webhook/, events payment.captured, refund.processed, refund.failed,
    and put the webhook secret in RAZORPAY_WEBHOOK_SECRET.
    """

    authentication_classes = []
    permission_classes = []

    def post(self, request):
        if not payments.verify_webhook_signature(request.body, request.headers.get("X-Razorpay-Signature")):
            return Response({"detail": "Invalid signature."}, status=status.HTTP_400_BAD_REQUEST)
        event = request.data.get("event", "")
        entity = request.data.get("payload", {})
        if event in ("payment.captured", "order.paid"):
            payment = entity.get("payment", {}).get("entity", {})
            booking = Booking.objects.filter(gateway_order_id=payment.get("order_id")).first()
            if booking:
                try:
                    services.finalize_gateway_payment(
                        booking.pk, payment.get("id"), payments.METHOD_MAP.get(payment.get("method"), "upi")
                    )
                except ValidationError:
                    pass  # hold expired and slot full: already refunded inside finalize
            else:
                # Combo pass orders are paid through the same Razorpay account.
                from passes import services as pass_services
                from passes.models import PassOrder

                order = PassOrder.objects.filter(gateway_order_id=payment.get("order_id")).first()
                if order:
                    try:
                        pass_services.finalize_gateway_payment(
                            order.pk, payment.get("id"), payments.METHOD_MAP.get(payment.get("method"), "upi")
                        )
                    except ValidationError:
                        pass
                else:
                    # Heritage Card (membership) purchases too.
                    from memberships import services as membership_services
                    from memberships.models import Membership

                    membership = Membership.objects.filter(gateway_order_id=payment.get("order_id")).first()
                    if membership:
                        try:
                            membership_services.finalize_gateway_payment(
                                membership.pk, payment.get("id"), payments.METHOD_MAP.get(payment.get("method"), "upi")
                            )
                        except ValidationError:
                            pass  # paid after an admin cancelled it: refunded inside finalize
                    else:
                        # Donations (80G receipts) as well.
                        from donations import services as donation_services
                        from donations.models import Donation

                        donation = Donation.objects.filter(gateway_order_id=payment.get("order_id")).first()
                        if donation:
                            donation_services.finalize_gateway_payment(
                                donation.pk, payment.get("id"), payments.METHOD_MAP.get(payment.get("method"), "upi")
                            )
        elif event in ("refund.processed", "refund.failed"):
            from memberships.models import Membership
            from passes.models import PassOrder

            refund = entity.get("refund", {}).get("entity", {})
            processed = event == "refund.processed"
            Booking.objects.filter(refund_id=refund.get("id")).update(
                refund_status=Booking.RefundStatus.PROCESSED if processed else Booking.RefundStatus.FAILED
            )
            PassOrder.objects.filter(refund_id=refund.get("id")).update(
                refund_status=PassOrder.RefundStatus.PROCESSED if processed else PassOrder.RefundStatus.FAILED
            )
            Membership.objects.filter(refund_id=refund.get("id")).update(
                refund_status=Membership.RefundStatus.PROCESSED if processed else Membership.RefundStatus.FAILED
            )
        return Response({"ok": True})


class DashboardView(APIView):
    """Panel dashboard. Totals and charts come from the pre-calculated stats.DailyStat (refreshed lazily, see
    stats/services.py); only the "recent" list reads bookings."""

    permission_classes = [IsPanelUser]

    def get(self, request):
        from django.core.cache import cache

        key = f"dashboard:v2:{request.user.pk}:{timezone.localdate()}"
        data = cache.get(key)
        if data is None:
            data = self.build(request)
            cache.set(key, data, 60)
        return Response(data)

    def build(self, request):
        from collections import defaultdict
        from decimal import Decimal

        from stats import services as stats
        from stats.models import StatusGroup

        stats.expire_stale_bookings()
        today = timezone.localdate()
        start = today - datetime.timedelta(days=13)
        scoped = panel_bookings(request.user)  # raises for staff without a place
        rows = stats.panel_stats(request.user)
        stats.ensure_fresh(start, today, all_dirty=True)

        # One pass over the stats for every all-time figure (~1,000 groups), folded in Python.
        groups = (
            rows.order_by().values("museum_id", "channel", "is_group", "status_group")
            .annotate(n=Sum("bookings"), checked=Sum("checked_in_bookings"),
                      v=Sum("visitors"), rev=Sum("revenue"))
        )
        zero = Decimal("0.00")
        totals = {"revenue": zero, "visitors": 0, "bookings": 0}
        status_counts = defaultdict(int)
        museums = defaultdict(lambda: {"revenue": zero, "visitors": 0, "bookings": 0})
        channels = defaultdict(lambda: {"bookings": 0, "revenue": zero, "visitors": 0})
        group_n = group_visitors = 0
        for g in groups:
            n = g["n"] or 0
            if not n:
                continue
            if g["status_group"] != StatusGroup.PAID:
                status_counts[g["status_group"]] += n
                continue
            checked = g["checked"] or 0
            if n - checked:
                status_counts[Booking.Status.CONFIRMED] += n - checked
            if checked:
                status_counts[Booking.Status.CHECKED_IN] += checked
            revenue, visitors = g["rev"] or zero, g["v"] or 0
            totals["revenue"] += revenue
            totals["visitors"] += visitors
            totals["bookings"] += n
            for bucket in (museums[g["museum_id"]], channels[g["channel"]]):
                bucket["revenue"] += revenue
                bucket["visitors"] += visitors
                bucket["bookings"] += n
            if g["is_group"]:
                group_n += n
                group_visitors += visitors

        info = stats.museum_info(museums)
        top_museums = sorted(museums.items(), key=lambda kv: kv[1]["revenue"], reverse=True)[:8]
        states = defaultdict(lambda: {"visitors": 0, "revenue": zero})
        for museum_id, m in museums.items():
            state = states[info.get(museum_id, {}).get("city__state__name")]
            state["visitors"] += m["visitors"]
            state["revenue"] += m["revenue"]
        by_state = sorted(states.items(), key=lambda kv: kv[1]["visitors"], reverse=True)[:10]

        by_day = {
            r["date"]: r
            for r in rows.filter(date__gte=start, date__lte=today, status_group=StatusGroup.PAID)
            .order_by().values("date").annotate(n=Sum("bookings"), rev=Sum("revenue"))
        }
        daily = []
        for offset in range(14):
            day = start + datetime.timedelta(days=offset)
            row = by_day.get(day, {})
            daily.append({"date": day, "bookings": row.get("n") or 0, "revenue": row.get("rev") or 0})

        today_stats = rows.filter(date=today).aggregate(
            expected=Sum("visit_visitors", filter=Q(status_group=StatusGroup.PAID)),
            checked_in=Sum("visit_checked_in_visitors"),
        )
        recent = scoped.select_related(
            "museum__city__state", "slot", "event_session__event", "user", "membership"
        ).prefetch_related("items", "addons")[:8]

        return {
            "totals": {
                "revenue": totals["revenue"] if totals["bookings"] else 0,
                "visitors": totals["visitors"],
                "bookings": totals["bookings"],
                "expected_today": today_stats["expected"] or 0,
                "checked_in_today": today_stats["checked_in"] or 0,
                "museums": Museum.for_panel_user(request.user).filter(is_active=True).count(),
                "users": get_user_model().objects.count(),
                "group_bookings": group_n,
                "group_visitors": group_visitors,
            },
            "daily": daily,
            "top_museums": [
                {"name": info.get(mid, {}).get("name"), "slug": info.get(mid, {}).get("slug"),
                 "revenue": m["revenue"], "visitors": m["visitors"]}
                for mid, m in top_museums
            ],
            "by_state": [
                {"state": state, "visitors": v["visitors"], "revenue": v["revenue"]}
                for state, v in by_state
            ],
            "status_counts": dict(status_counts),
            "by_channel": {
                channel: {"bookings": c["bookings"], "revenue": c["revenue"], "visitors": c["visitors"]}
                for channel, c in channels.items()
            },
            "recent": BookingSerializer(recent, many=True).data,
        }


# --- Gates, combo-pass check-in and live occupancy ---------------------------------------------------------

def gate_for(museum, gate_id, strict=False):
    """The museum's gate with this id, or None. strict=True rejects an id that isn't a gate of this museum."""
    if gate_id in (None, ""):
        return None
    try:
        gate = Gate.objects.filter(pk=int(gate_id), museum=museum).first()
    except (TypeError, ValueError):
        gate = None
    if gate is None and strict:
        raise ValidationError({"gate": f"This gate is not at {museum.name}. Choose the gate again."})
    return gate


def tag_scan_gate(booking, gate, scan_id=None):
    """Record which gate admitted the scan just created by services.mark_checked_in."""
    if gate is None:
        return
    scans = GateScan.objects.filter(booking=booking)
    scan = scans.filter(scan_id=scan_id).first() if scan_id else scans.order_by("-id").first()
    if scan and scan.gate_id is None:
        scan.gate = gate
        scan.save(update_fields=["gate"])


def checkin_pass(request, reference):
    """Online check-in of a combo pass at the chosen museum: the whole party, once per place."""
    from passes import services as pass_services

    museum = Museum.objects.filter(slug=request.data.get("museum") or "").first()
    if not museum:
        raise ValidationError({"reference": "Choose the place you are checking in at first."})
    ensure_museum_access(request.user, museum)
    gate = gate_for(museum, request.data.get("gate"), strict=True)
    with transaction.atomic():
        order = pass_services.lock_order(reference)
        if not order:
            raise ValidationError({"reference": "No pass found with this reference."})
        pass_services.admit(order, museum, request.user, gate=gate)
    return Response(pass_services.checkin_payload(order, museum))


def sync_pass_entry(museum, ref, at, scan_id, user, gate):
    """One offline pass scan from checkin-sync. Re-sending the same scan_id is harmless."""
    from passes import services as pass_services
    from passes.models import PassVisit

    with transaction.atomic():
        if scan_id and PassVisit.objects.filter(scan_id=scan_id).exists():
            return {"reference": ref, "result": "ok", "detail": ""}
        order = pass_services.lock_order(ref)
        if not order:
            return {"reference": ref, "result": "invalid", "detail": "Pass not found."}
        used = order.visits.filter(museum=museum).first()
        if used:
            first = timezone.localtime(used.visited_at).strftime("%H:%M")
            return {"reference": ref, "result": "duplicate", "detail": f"This pass was already used here (at {first})."}
        error = pass_services.admission_error(order, museum, timezone.localdate(at))
        if error:
            return {"reference": ref, "result": "invalid", "detail": error}
        pass_services.admit(order, museum, user, at=at, scan_id=scan_id, offline=True, gate=gate)
    return {"reference": ref, "result": "ok", "detail": ""}


class OccupancyView(APIView):
    """Live occupancy for one place today: GET /api/admin/occupancy/?museum=<slug>[&date=YYYY-MM-DD].

    Per slot: expected visitors (paid bookings), entered (gate scans of that slot's tickets; combo-pass entries
    are placed in the slot whose time window contains the scan), and entries per gate.

    "Inside now" is an ESTIMATE: there are no exit scans, so we assume a visit lasts about two slots and count
    everyone who entered in the current slot and the previous one (before the first slot: entries of the first
    slot; after closing time: 0). Its percentage is against the capacity of those same slots.
    """

    permission_classes = [IsPanelUser]

    def get(self, request):
        from passes.models import PassOrder, PassVisit

        slug = request.query_params.get("museum") or ""
        if slug:
            museum = Museum.objects.filter(slug=slug).first()
            if not museum:
                raise ValidationError({"museum": "Unknown place."})
            ensure_museum_access(request.user, museum)
        else:
            museum = Museum.for_panel_user(request.user).filter(is_active=True).order_by("name").first()
            if not museum:
                raise ValidationError({"museum": "Pass ?museum=<slug>."})
        today = timezone.localdate()
        day = parse_date(request.query_params.get("date", "") or "") or today
        now = timezone.localtime()
        slots = list(museum.slots.filter(is_active=True).order_by("start_time"))
        gates = list(museum.gates.all())
        gate_names = {g.id: g.name for g in gates}

        expected = dict(
            Booking.objects.filter(museum=museum, visit_date=day, status__in=PAID, event_session__isnull=True)
            .values("slot_id").annotate(n=Sum("total_visitors")).values_list("slot_id", "n")
        )
        # (slot_id, gate_id) -> people admitted
        entered = {}
        for row in (
            GateScan.objects.filter(booking__museum=museum, booking__visit_date=day, booking__event_session__isnull=True)
            .values("booking__slot_id", "gate_id").annotate(n=Sum("admitted"))
        ):
            key = (row["booking__slot_id"], row["gate_id"])
            entered[key] = entered.get(key, 0) + row["n"]

        def slot_at(moment_time):
            started = [s for s in slots if s.start_time <= moment_time]
            return (started[-1] if started else slots[0]) if slots else None

        pass_entered = {}
        visits = [
            v for v in PassVisit.objects.filter(museum=museum, visited_at__date__gte=day - datetime.timedelta(days=1))
            if timezone.localtime(v.visited_at).date() == day
        ]
        for v in visits:
            slot = slot_at(timezone.localtime(v.visited_at).time())
            key = (slot.id if slot else None, v.gate_id)
            entered[key] = entered.get(key, 0) + v.admitted
            pass_entered[key[0]] = pass_entered.get(key[0], 0) + v.admitted
        pass_expected = sum(
            o.total_visitors for o in PassOrder.objects.filter(
                status=PassOrder.Status.CONFIRMED, combo_pass__sites__museum=museum,
                start_date__lte=day, start_date__gte=day - datetime.timedelta(days=14),
            ).distinct() if o.end_date >= day
        )

        # Which slots count as "inside now".
        current_idx = None
        if day == today and slots:
            started = [i for i, s in enumerate(slots) if s.start_time <= now.time()]
            current_idx = started[-1] if started else -1
        if day == today and now.time() > museum.closing_time:
            counted = []
        elif current_idx is None:
            counted = []
        elif current_idx == -1:
            counted = [0]
        else:
            counted = [i for i in (current_idx - 1, current_idx) if i >= 0]

        gate_keys = [g.id for g in gates] + ([None] if any(k[1] is None for k in entered) else [])
        slot_rows = []
        for i, s in enumerate(slots):
            by_gate = {gid: entered.get((s.id, gid), 0) for gid in gate_keys}
            n_entered = sum(by_gate.values())
            n_expected = expected.get(s.id, 0)
            slot_rows.append({
                "slot_id": s.id,
                "start": s.start_time,
                "end": s.end_time,
                "capacity": s.capacity,
                "expected": n_expected,
                "entered": n_entered,
                "pass_entered": pass_entered.get(s.id, 0),
                "by_gate": [
                    {"gate_id": gid, "name": gate_names.get(gid, "Not recorded"), "entered": n}
                    for gid, n in by_gate.items()
                ],
                "booked_pct": round(n_expected * 100 / s.capacity) if s.capacity else 0,
                "is_current": current_idx == i,
                "counted_inside": i in counted,
            })
        inside = sum(slot_rows[i]["entered"] for i in counted)
        inside_capacity = sum(slot_rows[i]["capacity"] for i in counted)
        total_expected = sum(r["expected"] for r in slot_rows) + pass_expected
        total_entered = sum(entered.values())
        gate_rows = []
        for gid in gate_keys:
            gate_rows.append({
                "gate_id": gid,
                "name": gate_names.get(gid, "Not recorded"),
                "is_active": next((g.is_active for g in gates if g.id == gid), True),
                "entered": sum(n for (sid, g), n in entered.items() if g == gid),
                "inside_estimate": sum(entered.get((slot_rows[i]["slot_id"], gid), 0) for i in counted),
            })
        return Response({
            "museum": museum.slug,
            "museum_name": museum.name,
            "date": day,
            "generated_at": timezone.now(),
            "is_today": day == today,
            "totals": {
                "expected": total_expected,
                "pass_expected": pass_expected,
                "entered": total_entered,
                "entered_pct": round(total_entered * 100 / total_expected) if total_expected else 0,
                "inside_estimate": inside if day == today else None,
                "inside_capacity": inside_capacity,
                "inside_pct": round(inside * 100 / inside_capacity) if inside_capacity else 0,
                "capacity_today": sum(s.capacity for s in slots),
            },
            "estimate_note": (
                "Inside now is an estimate: people who entered in the current and the previous slot "
                "(no exit scans are recorded). After closing time it is 0."
            ),
            "slots": slot_rows,
            "gates": gate_rows,
        })


class GateSerializer(serializers.ModelSerializer):
    museum = serializers.SlugRelatedField(slug_field="slug", queryset=Museum.objects.all())
    museum_name = serializers.CharField(source="museum.name", read_only=True)

    class Meta:
        model = Gate
        fields = ("id", "museum", "museum_name", "name", "is_active", "sort_order")


class GateViewSet(viewsets.ModelViewSet):
    """Gates of a place: /api/admin/gates/?museum=<slug>. Panel users list their places' gates; admins edit."""

    serializer_class = GateSerializer
    pagination_class = None
    filter_backends = []

    def get_permissions(self):
        return [IsPanelUser()] if self.action in ("list", "retrieve") else [IsAdminRole()]

    def get_queryset(self):
        qs = Gate.objects.select_related("museum").filter(museum__in=Museum.for_panel_user(self.request.user))
        slug = self.request.query_params.get("museum")
        return qs.filter(museum__slug=slug) if slug else qs
