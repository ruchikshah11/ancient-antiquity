import datetime

from django.db import transaction
from django.db.models import Count, Q
from django.utils import timezone
from django.utils.dateparse import parse_date
from rest_framework import mixins, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import NotFound, PermissionDenied, ValidationError
from rest_framework.response import Response
from rest_framework.views import APIView

from accounts.permissions import IsAdminRole, IsPanelUser
from bookings import services as booking_services
from museums.models import Museum

from . import services
from .emails import send_school_status, send_trip_decision
from .models import School, SchoolTrip
from .serializers import (
    ApproveSerializer,
    DeclineSerializer,
    EstimateSerializer,
    SchoolDecisionSerializer,
    SchoolSerializer,
    SchoolTripCreateSerializer,
    SchoolTripSerializer,
    estimate_data,
)


class MySchoolView(APIView):
    """The signed-in teacher's school. GET (404 when none), POST to register, PATCH to update.

    Editing a rejected school sends it back for verification; a verified school may only change contacts.
    """

    def get_school(self, request):
        school = School.objects.select_related("state", "verified_by", "owner").filter(owner=request.user).first()
        if school is None:
            raise NotFound("You have not registered a school yet.")
        return school

    def get(self, request):
        return Response(SchoolSerializer(self.get_school(request)).data)

    def post(self, request):
        if School.objects.filter(owner=request.user).exists():
            raise ValidationError("Your account already has a school. Edit it instead.")
        data = request.data.copy() if hasattr(request.data, "copy") else dict(request.data)
        user = request.user
        data.setdefault("contact_name", f"{user.first_name} {user.last_name}".strip())
        data.setdefault("contact_email", user.email)
        data.setdefault("contact_phone", user.phone)
        serializer = SchoolSerializer(data=data)
        serializer.is_valid(raise_exception=True)
        school = serializer.save(owner=user)
        return Response(SchoolSerializer(school).data, status=status.HTTP_201_CREATED)

    def patch(self, request):
        school = self.get_school(request)
        serializer = SchoolSerializer(school, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        extra = {}
        if school.status == School.Status.REJECTED:
            extra = {"status": School.Status.PENDING, "rejection_reason": ""}
        school = serializer.save(**extra)
        return Response(SchoolSerializer(school).data)


class EstimateView(APIView):
    """POST {museum, date?, students, young_students?, teachers, helpers?}: the price of a class visit."""

    def post(self, request):
        serializer = EstimateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        d = serializer.validated_data
        day = d.get("date") or timezone.localdate() + datetime.timedelta(days=1)
        est = services.estimate(d["museum"], day, d["students"], d["teachers"], d["helpers"], d["young_students"])
        data = estimate_data(est)
        data["date"] = day
        data["date_error"] = services.visit_day_error(d["museum"], day) if d.get("date") else None
        return Response(data)


class SchoolViewSet(mixins.ListModelMixin, mixins.RetrieveModelMixin, viewsets.GenericViewSet):
    """Admin: registered schools. Filters ?status=, ?state=<id>, ?search=. Actions verify / reject."""

    serializer_class = SchoolSerializer
    permission_classes = [IsAdminRole]
    search_fields = ["name", "city", "udise_code", "contact_name", "contact_email", "owner__email"]
    ordering_fields = ["created_at", "name"]
    filterset_fields = []
    lookup_value_regex = r"\d+"

    def get_queryset(self):
        qs = School.objects.select_related("state", "verified_by", "owner").annotate(n_trips=Count("trips")).order_by("-created_at")
        params = self.request.query_params
        if params.get("status"):
            qs = qs.filter(status=params["status"])
        if params.get("state"):
            qs = qs.filter(state_id=params["state"])
        return qs

    def _decide(self, request, new_status):
        serializer = SchoolDecisionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        reason = serializer.validated_data.get("reason", "").strip()
        if new_status == School.Status.REJECTED and not reason:
            raise ValidationError({"reason": "Tell the teacher why the school was rejected."})
        school = self.get_object()
        school.status = new_status
        school.rejection_reason = reason if new_status == School.Status.REJECTED else ""
        school.verified_by = request.user
        school.verified_at = timezone.now()
        school.save()
        transaction.on_commit(lambda: send_school_status(school.pk))
        return Response(SchoolSerializer(self.get_queryset().get(pk=school.pk)).data)

    @action(detail=True, methods=["post"])
    def verify(self, request, pk=None):
        return self._decide(request, School.Status.VERIFIED)

    @action(detail=True, methods=["post"])
    def reject(self, request, pk=None):
        return self._decide(request, School.Status.REJECTED)


class SchoolTripViewSet(
    mixins.ListModelMixin, mixins.RetrieveModelMixin, mixins.CreateModelMixin, viewsets.GenericViewSet
):
    """Class trips. Teachers create and see their school's trips (also panel users with ?mine=1); staff see
    trips for their assigned places, admins all.

    Filters: ?status=, ?museum=<slug>, ?date=YYYY-MM-DD (preferred, alternative or approved date), ?search=
    """

    serializer_class = SchoolTripSerializer
    search_fields = ["school__name", "school__contact_name", "school__contact_email", "museum__name", "grades"]
    ordering_fields = ["created_at", "preferred_date", "students"]
    filterset_fields = []
    lookup_value_regex = r"\d+"
    STAFF_ACTIONS = {"approve", "decline", "complete", "slots"}

    def get_queryset(self):
        booking_services.expire_stale_bookings()
        qs = SchoolTrip.objects.select_related(
            "school", "museum__city", "decided_by", "booking__museum__city__state", "booking__slot", "booking__user",
        ).prefetch_related("booking__items")
        user, params = self.request.user, self.request.query_params
        if not user.is_panel_user or params.get("mine"):
            qs = qs.filter(school__owner=user)
        elif not user.is_admin_role:
            qs = qs.filter(Q(museum__in=Museum.for_panel_user(user)) | Q(school__owner=user))
        if params.get("status"):
            qs = qs.filter(status=params["status"])
        if params.get("museum"):
            qs = qs.filter(museum__slug=params["museum"])
        day = parse_date(params.get("date") or "")
        if day:
            qs = qs.filter(Q(preferred_date=day) | Q(alternative_date=day) | Q(approved_date=day))
        return qs

    def get_object(self):
        obj = super().get_object()
        user = self.request.user
        if self.action in self.STAFF_ACTIONS and not user.is_admin_role and not obj.museum.staff.filter(pk=user.pk).exists():
            raise PermissionDenied("You are not assigned to this place.")
        return obj

    def locked(self):
        obj = self.get_object()
        return SchoolTrip.objects.select_for_update().select_related("school", "museum", "booking").get(pk=obj.pk)

    def out(self, trip):
        return SchoolTripSerializer(self.get_queryset().get(pk=trip.pk)).data

    def create(self, request, *args, **kwargs):
        school = School.objects.filter(owner=request.user).first()
        if school is None:
            raise PermissionDenied("Register your school first.")
        if not school.is_verified:
            raise PermissionDenied("Your school is waiting for verification. You can request trips once it is verified.")
        serializer = SchoolTripCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        d = serializer.validated_data
        est = services.estimate(d["museum"], d["preferred_date"], d["students"], d["teachers"], d["helpers"],
                                d["young_students"])
        trip = serializer.save(school=school, requested_by=request.user, estimated_amount=est["total"])
        return Response(self.out(trip), status=status.HTTP_201_CREATED)

    @action(detail=True, methods=["post"])
    def cancel(self, request, pk=None):
        with transaction.atomic():
            trip = self.locked()
            if trip.school.owner_id != request.user.id:
                raise PermissionDenied("Only the school's teacher can cancel this request.")
            if trip.status != SchoolTrip.Status.SUBMITTED:
                raise ValidationError("Only requests that are not yet approved can be cancelled here. "
                                      "Approved trips can be cancelled from My bookings.")
            trip.status = SchoolTrip.Status.CANCELLED
            trip.save(update_fields=["status", "updated_at"])
        return Response(self.out(trip))

    @action(detail=True, methods=["get"])
    def estimate(self, request, pk=None):
        """The trip's price on ?date= (default: preferred date), for the approval screen."""
        trip = self.get_object()
        day = parse_date(request.query_params.get("date") or "") or trip.preferred_date
        return Response({**estimate_data(services.estimate_for_trip(trip, day)), "date": day})

    # --- staff ---------------------------------------------------------------------------------------

    @action(detail=True, methods=["get"], permission_classes=[IsPanelUser])
    def slots(self, request, pk=None):
        """Free places and group room per slot on ?date= (default: preferred date)."""
        trip = self.get_object()
        day = parse_date(request.query_params.get("date") or "") or trip.preferred_date
        est = services.estimate_for_trip(trip, day)
        return Response({
            "date": day,
            "people": est["people"],
            "date_error": services.visit_day_error(trip.museum, day),
            "slots": services.slot_room(trip.museum, day),
        })

    @action(detail=True, methods=["post"], permission_classes=[IsPanelUser])
    def approve(self, request, pk=None):
        serializer = ApproveSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        d = serializer.validated_data
        with transaction.atomic():
            trip = self.locked()
            if trip.status != SchoolTrip.Status.SUBMITTED:
                raise ValidationError(f"This trip is {trip.get_status_display().lower()} and can't be approved.")
            day = d.get("date") or trip.preferred_date
            if day not in (trip.preferred_date, trip.alternative_date):
                raise ValidationError({"date": "Approve the preferred or the alternative date."})
            slot = d.get("slot")
            if slot is not None and slot.museum_id != trip.museum_id:
                raise ValidationError({"slot": "This slot does not belong to the place."})
            services.approve_trip(trip, by_user=request.user, visit_date=day, slot=slot,
                                  quoted_amount=d.get("quoted_amount"), staff_note=d.get("staff_note"))
        return Response(self.out(trip))

    @action(detail=True, methods=["post"], permission_classes=[IsPanelUser])
    def decline(self, request, pk=None):
        serializer = DeclineSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        with transaction.atomic():
            trip = self.locked()
            if trip.status not in (SchoolTrip.Status.SUBMITTED, SchoolTrip.Status.APPROVED):
                raise ValidationError(f"This trip is {trip.get_status_display().lower()} and can't be declined.")
            if services.is_paid(trip):
                raise ValidationError("This trip is already paid. Cancel its booking from Bookings first.")
            services.release_booking(trip)
            trip.status = SchoolTrip.Status.DECLINED
            trip.staff_note = serializer.validated_data["reason"].strip()
            trip.decided_by = request.user
            trip.decided_at = timezone.now()
            trip.save()
            transaction.on_commit(lambda: send_trip_decision(trip.pk))
        return Response(self.out(trip))

    @action(detail=True, methods=["post"], permission_classes=[IsPanelUser])
    def complete(self, request, pk=None):
        with transaction.atomic():
            trip = self.locked()
            if trip.status != SchoolTrip.Status.APPROVED or not services.is_paid(trip):
                raise ValidationError("Only approved and paid trips can be marked completed.")
            trip.status = SchoolTrip.Status.COMPLETED
            trip.completed_at = timezone.now()
            trip.save(update_fields=["status", "completed_at", "updated_at"])
        return Response(self.out(trip))
