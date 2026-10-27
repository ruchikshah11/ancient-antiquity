import datetime

from django.conf import settings
from django.db.models import Count, Min, OuterRef, ProtectedError, Q, Subquery, Sum
from django.db.models.functions import Coalesce
from django.db import transaction
from django.utils import timezone
from django.utils.dateparse import parse_date
from rest_framework import mixins, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from accounts.permissions import IsAdminRole, IsPanelUser
from bookings.models import Booking
from bookings.serializers import BookingSerializer
from bookings.services import expire_stale_bookings
from museums.models import Museum, PlaceClosure

from . import services
from .models import Event, EventPrice, EventSession, WaitlistEntry
from .serializers import (
    EventAdminSerializer,
    EventBookingCreateSerializer,
    EventDetailSerializer,
    EventListSerializer,
    EventPriceAdminSerializer,
    EventSessionAdminSerializer,
    GenerateSessionsSerializer,
    WaitlistCreateSerializer,
    WaitlistEntrySerializer,
)

LIST_DAYS = 60  # default look-ahead for the events list


def _date_param(request, name, default):
    try:
        return parse_date(request.query_params.get(name) or "") or default
    except ValueError:
        return default


def _upcoming_q(prefix, start, end):
    now = timezone.localtime()
    return (
        Q(**{f"{prefix}is_active": True, f"{prefix}date__gte": start, f"{prefix}date__lte": end})
        & ~Q(**{f"{prefix}date": now.date(), f"{prefix}start_time__lte": now.time()})
    )


class EventViewSet(viewsets.ReadOnlyModelViewSet):
    """Public: GET /api/events/?museum=&kind=&state=&from=&to=&featured=1 and GET /api/events/<slug>/."""

    permission_classes = [AllowAny]
    lookup_field = "slug"
    pagination_class = None
    filter_backends = []

    def get_serializer_class(self):
        return EventDetailSerializer if self.action == "retrieve" else EventListSerializer

    def get_queryset(self):
        today = timezone.localdate()
        start = max(_date_param(self.request, "from", today), today)
        end = _date_param(self.request, "to", today + datetime.timedelta(days=LIST_DAYS))
        upcoming = _upcoming_q("sessions__", start, end)
        qs = (
            Event.objects.filter(is_active=True, museum__is_active=True)
            .select_related("museum__city__state")
            .prefetch_related("prices")
            .annotate(
                next_date=Min("sessions__date", filter=upcoming),
                upcoming_sessions=Count("sessions", filter=upcoming, distinct=True),
            )
        )
        if self.action == "list":
            qs = qs.filter(upcoming_sessions__gt=0)
            params = self.request.query_params
            if params.get("museum"):
                qs = qs.filter(museum__slug=params["museum"])
            if params.get("kind"):
                qs = qs.filter(kind=params["kind"])
            if params.get("state"):
                state = params["state"]
                qs = qs.filter(museum__city__state_id=state) if state.isdigit() else qs.filter(
                    museum__city__state__name__iexact=state
                )
            if params.get("featured") in ("1", "true"):
                qs = qs.filter(featured=True)
            if params.get("q"):
                qs = qs.filter(Q(title__icontains=params["q"]) | Q(museum__name__icontains=params["q"]))
            qs = qs.order_by("-featured", "next_date", "title")
        return qs

    def retrieve(self, request, *args, **kwargs):
        expire_stale_bookings()
        event = self.get_object()
        return Response(EventDetailSerializer(event, context={"sessions": session_rows(event)}).data)


def session_rows(event):
    """Upcoming sessions with availability (inside the booking window)."""
    today = timezone.localdate()
    end = today + datetime.timedelta(days=settings.BOOKING_WINDOW_DAYS)
    sessions = list(event.sessions.filter(_upcoming_q("", today, end)).order_by("date", "start_time"))
    taken = services.taken_by_session([s.pk for s in sessions])
    closures = list(PlaceClosure.covering(event.museum, today, end).filter(all_day=True))
    rows = []
    for s in sessions:
        closed = next((c.reason for c in closures if c.start_date <= s.date <= c.end_date), "")
        available = 0 if closed else max(s.capacity - taken.get(s.pk, 0), 0)
        rows.append({
            "id": s.pk, "date": s.date, "start_time": s.start_time, "end_time": s.end_time,
            "capacity": s.capacity, "available": available, "sold_out": not closed and available == 0,
            "closed_reason": closed,
        })
    return rows


class EventBookingView(APIView):
    """POST /api/events/bookings/: pending booking for an event session, paid via /api/bookings/<ref>/pay/."""

    permission_classes = [IsAuthenticated]

    def post(self, request):
        serializer = EventBookingCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        booking = services.create_event_booking(user=request.user, **serializer.validated_data)
        booking = Booking.objects.select_related("museum__city__state", "event_session__event", "user").get(pk=booking.pk)
        return Response(BookingSerializer(booking).data, status=status.HTTP_201_CREATED)


class WaitlistViewSet(mixins.ListModelMixin, mixins.CreateModelMixin, mixins.DestroyModelMixin, viewsets.GenericViewSet):
    """The signed-in visitor's waitlist: GET/POST /api/waitlist/, DELETE /api/waitlist/<id>/."""

    permission_classes = [IsAuthenticated]
    serializer_class = WaitlistEntrySerializer
    pagination_class = None
    filter_backends = []

    def get_queryset(self):
        services.expire_past_entries()
        return WaitlistEntry.objects.filter(user=self.request.user).select_related(
            "museum", "slot", "event_session__event"
        ).order_by("-created_at")

    def list(self, request, *args, **kwargs):
        qs = self.get_queryset()
        if request.query_params.get("all") not in ("1", "true"):
            qs = qs.filter(status__in=[WaitlistEntry.Status.WAITING, WaitlistEntry.Status.NOTIFIED])
        return Response(WaitlistEntrySerializer(qs, many=True).data)

    def create(self, request, *args, **kwargs):
        serializer = WaitlistCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        expire_stale_bookings()
        slot, session = data.get("slot"), data.get("event_session")
        free = services.session_free(session) if session else services.slot_free(slot, data["visit_date"])
        if free >= data["quantity"]:
            raise ValidationError({"detail": f"There are still {free} seat(s) free. Book them now instead."})
        with transaction.atomic():
            existing = WaitlistEntry.objects.select_for_update().filter(
                user=request.user, slot=slot, event_session=session, visit_date=data["visit_date"],
                status__in=[WaitlistEntry.Status.WAITING, WaitlistEntry.Status.NOTIFIED],
            ).first()
            if existing:
                existing.quantity = data["quantity"]
                existing.notify_channels = data["notify_channels"]
                existing.status = WaitlistEntry.Status.WAITING
                existing.notified_at = None
                existing.save(update_fields=["quantity", "notify_channels", "status", "notified_at"])
                entry, code = existing, status.HTTP_200_OK
            else:
                entry = WaitlistEntry.objects.create(
                    user=request.user, museum=data["museum"], slot=slot, event_session=session,
                    visit_date=data["visit_date"], quantity=data["quantity"], notify_channels=data["notify_channels"],
                )
                code = status.HTTP_201_CREATED
        return Response(WaitlistEntrySerializer(entry).data, status=code)


# --- Admin -----------------------------------------------------------------------------------------------

class _PanelReadAdminWrite:
    def get_permissions(self):
        return [IsPanelUser()] if self.action in ("list", "retrieve") else [IsAdminRole()]


def _protected_delete(instance, what):
    try:
        instance.delete()
    except ProtectedError:
        raise ValidationError(f"This {what} has bookings, so it can't be deleted. Deactivate it instead.")
    return Response(status=status.HTTP_204_NO_CONTENT)


class AdminEventViewSet(_PanelReadAdminWrite, viewsets.ModelViewSet):
    """/api/admin/events/?museum=<slug>: staff see their places' events; admins create/edit/delete."""

    serializer_class = EventAdminSerializer
    pagination_class = None
    filter_backends = []

    def get_queryset(self):
        today = timezone.localdate()
        qs = (
            Event.objects.filter(museum__in=Museum.for_panel_user(self.request.user))
            .select_related("museum").prefetch_related("prices")
            .annotate(
                sessions_count=Count("sessions", distinct=True),
                upcoming_sessions=Count("sessions", filter=Q(sessions__date__gte=today, sessions__is_active=True), distinct=True),
            )
            .order_by("museum__name", "title")
        )
        slug = self.request.query_params.get("museum")
        return qs.filter(museum__slug=slug) if slug else qs

    def destroy(self, request, *args, **kwargs):
        return _protected_delete(self.get_object(), "event")

    @action(detail=True, methods=["post"], url_path="generate-sessions")
    def generate_sessions(self, request, pk=None):
        event = self.get_object()
        serializer = GenerateSessionsSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        d = serializer.validated_data
        existing = set(event.sessions.filter(date__gte=d["start_date"], date__lte=d["end_date"], start_time=d["start_time"])
                       .values_list("date", flat=True))
        new, day = [], d["start_date"]
        while day <= d["end_date"]:
            if (not d["weekdays"] or day.weekday() in d["weekdays"]) and day not in existing:
                new.append(EventSession(event=event, date=day, start_time=d["start_time"], end_time=d["end_time"],
                                        capacity=d["capacity"]))
            day += datetime.timedelta(days=1)
        EventSession.objects.bulk_create(new)
        return Response({"created": len(new), "skipped": len(existing)}, status=status.HTTP_201_CREATED)


class AdminEventSessionViewSet(_PanelReadAdminWrite, viewsets.ModelViewSet):
    """/api/admin/event-sessions/?event=<id>[&from=YYYY-MM-DD]."""

    serializer_class = EventSessionAdminSerializer
    pagination_class = None
    filter_backends = []

    def get_queryset(self):
        qs = (
            EventSession.objects.filter(event__museum__in=Museum.for_panel_user(self.request.user))
            .annotate(
                booked=Coalesce(Subquery(
                    Booking.objects.filter(event_session=OuterRef("pk"))
                    .filter(status__in=[Booking.Status.CONFIRMED, Booking.Status.CHECKED_IN])
                    .order_by().values("event_session").annotate(n=Sum("total_visitors")).values("n")[:1]
                ), 0),
                waiting=Count("waitlist_entries", filter=Q(waitlist_entries__status=WaitlistEntry.Status.WAITING), distinct=True),
            )
            .order_by("date", "start_time")
        )
        params = self.request.query_params
        if params.get("event"):
            qs = qs.filter(event_id=params["event"])
        start = parse_date(params.get("from") or "")
        if start:
            qs = qs.filter(date__gte=start)
        return qs

    def perform_create(self, serializer):
        self._check_event(serializer.validated_data.get("event"))
        serializer.save()

    def perform_update(self, serializer):
        self._check_event(serializer.validated_data.get("event"))
        session = serializer.save()
        # More capacity may let waitlisted visitors in.
        transaction.on_commit(lambda: services.notify_waitlist_for(event_session_id=session.pk))

    def _check_event(self, event):
        if event and not Museum.for_panel_user(self.request.user).filter(pk=event.museum_id).exists():
            raise PermissionDenied("You are not assigned to this museum.")

    def destroy(self, request, *args, **kwargs):
        return _protected_delete(self.get_object(), "session")


class AdminEventPriceViewSet(_PanelReadAdminWrite, viewsets.ModelViewSet):
    """/api/admin/event-prices/?event=<id>."""

    serializer_class = EventPriceAdminSerializer
    pagination_class = None
    filter_backends = []

    def get_queryset(self):
        qs = EventPrice.objects.filter(event__museum__in=Museum.for_panel_user(self.request.user)).order_by("sort", "id")
        event = self.request.query_params.get("event")
        return qs.filter(event_id=event) if event else qs
