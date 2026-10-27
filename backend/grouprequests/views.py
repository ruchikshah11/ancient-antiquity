import datetime

from django.conf import settings
from django.db import transaction
from django.db.models import Prefetch, Q
from django.utils import timezone
from django.utils.dateparse import parse_date
from rest_framework import mixins, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.permissions import AllowAny
from rest_framework.response import Response

from accounts.permissions import IsPanelUser
from bookings import services
from bookings.models import Booking
from museums.models import Museum

from . import pricing
from .models import GroupRequest
from .serializers import (
    ApproveSerializer,
    DeclineSerializer,
    GroupRequestCreateSerializer,
    GroupRequestSerializer,
    MarkPaidSerializer,
    QuoteSerializer,
    can_cancel,
)

PAY_BY_DEFAULT_DAYS = 7


class GroupRequestViewSet(
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    mixins.CreateModelMixin,
    viewsets.GenericViewSet,
):
    """Large group visit requests (more than GROUP_MAX_SIZE people).

    Visitors create and see their own; staff/admin see all (unless ?mine=1) and review, plan, approve,
    decline and mark them paid.
    Filters: ?status= (or status=open for submitted + under review), ?museum=<slug>, ?date=YYYY-MM-DD, ?search=
    """

    serializer_class = GroupRequestSerializer
    search_fields = ["organisation_name", "contact_name", "contact_email", "contact_phone", "museum__name"]
    ordering_fields = ["created_at", "preferred_date", "participants"]
    filterset_fields = []

    def get_queryset(self):
        services.expire_stale_bookings()
        qs = GroupRequest.objects.select_related("museum__city", "requester", "decided_by").prefetch_related(
            Prefetch(
                "bookings",
                queryset=Booking.objects.select_related("museum__city__state", "slot", "user", "sold_by")
                .prefetch_related("items").order_by("slot__start_time"),
            )
        )
        user, params = self.request.user, self.request.query_params
        if not user.is_panel_user or params.get("mine"):
            qs = qs.filter(requester=user)
        elif not user.is_admin_role:
            # Staff: requests for the places assigned to them, plus their own.
            qs = qs.filter(Q(museum__in=Museum.for_panel_user(user)) | Q(requester=user))
        state = params.get("status")
        if state == "open":
            qs = qs.filter(status__in=GroupRequest.OPEN)
        elif state:
            qs = qs.filter(status=state)
        if params.get("museum"):
            qs = qs.filter(museum__slug=params["museum"])
        day = parse_date(params.get("date") or "")
        if day:
            qs = qs.filter(preferred_date=day)
        return qs

    def create(self, request, *args, **kwargs):
        serializer = GroupRequestCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        group_request = serializer.save(requester=request.user)
        return Response(self.out(group_request), status=status.HTTP_201_CREATED)

    def out(self, group_request):
        return GroupRequestSerializer(self.get_queryset().get(pk=group_request.pk)).data

    STAFF_ACTIONS = {"review", "plan", "approve", "decline", "mark_paid"}

    def get_object(self):
        obj = super().get_object()
        user = self.request.user
        if self.action in self.STAFF_ACTIONS and not user.is_admin_role and not obj.museum.staff.filter(pk=user.pk).exists():
            raise PermissionDenied("You are not assigned to this museum.")
        return obj

    def locked(self):
        """The request, row-locked (call inside a transaction)."""
        obj = self.get_object()
        return GroupRequest.objects.select_for_update().select_related("museum").get(pk=obj.pk)

    @action(detail=True, methods=["post"])
    def cancel(self, request, pk=None):
        with transaction.atomic():
            group_request = self.locked()
            if not can_cancel(group_request):
                raise ValidationError("This request can no longer be cancelled. Paid bookings can be cancelled from My bookings.")
            self._release_bookings(group_request)
            group_request.status = GroupRequest.Status.CANCELLED
            group_request.save(update_fields=["status", "updated_at"])
        return Response(self.out(group_request))

    @staticmethod
    def _release_bookings(group_request):
        group_request.bookings.filter(status=Booking.Status.PENDING).update(
            status=Booking.Status.CANCELLED, cancelled_at=timezone.now()
        )

    # --- staff ---------------------------------------------------------------------------------------

    @action(detail=True, methods=["post"], permission_classes=[IsPanelUser])
    def review(self, request, pk=None):
        """Mark a submitted request as under review (lets the visitor know someone is on it)."""
        group_request = self.get_object()
        if group_request.status == GroupRequest.Status.SUBMITTED:
            group_request.status = GroupRequest.Status.UNDER_REVIEW
            group_request.save(update_fields=["status", "updated_at"])
        return Response(self.out(group_request))

    @action(detail=True, methods=["get"], permission_classes=[IsPanelUser])
    def plan(self, request, pk=None):
        """Suggest a split over consecutive slots on ?date= (default: preferred date).

        ?time=morning|afternoon|any overrides the requested preferred time. Each slot keeps 20% free for individuals.
        """
        group_request = self.get_object()
        day = parse_date(request.query_params.get("date") or "") or group_request.preferred_date
        museum = group_request.museum
        closed = pricing.closed_message(museum, day)
        if closed:
            raise ValidationError({"date": closed})
        if day < timezone.localdate():
            raise ValidationError({"date": "This date is in the past."})
        people = group_request.participants + group_request.escorts
        preferred = request.query_params.get("time") or group_request.preferred_time
        result = services.plan_group_split(museum, day, people, preferred)
        note = ""
        if not result["fits"] and preferred != GroupRequest.PreferredTime.ANY:
            wider = services.plan_group_split(museum, day, people, GroupRequest.PreferredTime.ANY)
            if wider["fits"]:
                result, note = wider, f"Does not fit in the {preferred}; this plan uses the whole day."
        # split participants/escorts proportionally across the suggested slots
        escorts_left = group_request.escorts
        allocated = result["allocated"] or 1
        for k, alloc in enumerate(result["allocations"]):
            last = k == len(result["allocations"]) - 1
            e = escorts_left if last else min(escorts_left, round(group_request.escorts * alloc["people"] / allocated))
            e = min(e, alloc["people"])
            escorts_left -= e
            alloc["escorts"] = e
            alloc["participants"] = alloc["people"] - e
        # Slots closed by a partial closure that day: flag them and keep them out of the suggestion's wording.
        slot_closed = pricing.slot_closures(museum, day)
        for row in result["slots"]:
            row["closed_reason"] = slot_closed.get(row["slot_id"], "")
        blocked = [a for a in result["allocations"] if a["slot_id"] in slot_closed]
        if blocked:
            note = (note + " " if note else "") + "; ".join(
                f"The {a['start']:%H:%M} slot is closed ({slot_closed[a['slot_id']]}): move its people to another slot."
                for a in blocked
            )
        # Prices on the planned date (weekend / holiday / season rules), as the bookings will be charged.
        prices = pricing.ticket_prices(museum, day)
        ticket = services.default_group_ticket_type(museum)
        default_row = next((p for p in prices if ticket and p["id"] == ticket.id), None)
        if group_request.status == GroupRequest.Status.SUBMITTED:
            group_request.status = GroupRequest.Status.UNDER_REVIEW
            group_request.save(update_fields=["status", "updated_at"])
        return Response({
            **result,
            "date": day,
            "note": note,
            "reserve_percent": int(getattr(settings, "GROUP_REQUEST_INDIVIDUAL_RESERVE", 0.20) * 100),
            "default_ticket_type": default_row,
            "default_discount_percent": services.group_discount_percent(museum, group_request.group_type),
            "ticket_types": prices,  # price = effective price on `date`; base_price and rule show why
        })

    @action(detail=False, methods=["get"], permission_classes=[AllowAny])
    def quote(self, request):
        """Estimated price of a large group visit: ?museum=<slug>&date=&participants=&group_type=
        (staff may add &ticket_type=&discount_percent=). Uses the date's effective ticket prices and says
        whether the place is closed that day (`closed`: message or null)."""
        serializer = QuoteSerializer(data=request.query_params)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        staff = getattr(request.user, "is_panel_user", False)
        return Response(pricing.quote(
            data["museum"], data["date"], data["participants"], data["group_type"],
            ticket=data.get("ticket_type") if staff else None,
            discount_percent=data.get("discount_percent") if staff else None,
        ))

    @action(detail=True, methods=["post"], permission_classes=[IsPanelUser])
    def approve(self, request, pk=None):
        serializer = ApproveSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        today = timezone.localdate()
        with transaction.atomic():
            group_request = self.locked()
            museum = group_request.museum
            if group_request.status not in GroupRequest.OPEN:
                raise ValidationError(f"This request is {group_request.get_status_display().lower()} and can't be approved.")
            day = data["date"]
            if day < today or day > today + datetime.timedelta(days=settings.BOOKING_WINDOW_DAYS):
                raise ValidationError({"date": "Pick a date within the booking window."})
            closed = pricing.closed_message(museum, day)
            if closed:
                raise ValidationError({"date": closed})
            slot_closed = pricing.slot_closures(museum, day)

            default_ticket = data.get("ticket_type") or services.default_group_ticket_type(museum)
            if default_ticket is None or default_ticket.museum_id != museum.id:
                raise ValidationError({"ticket_type": "Choose a ticket type of this museum."})
            allocations, seen = [], set()
            for alloc in data["allocations"]:
                slot = alloc["slot"]
                if slot.museum_id != museum.id:
                    raise ValidationError({"allocations": "A slot does not belong to this museum."})
                if slot.pk in seen:
                    raise ValidationError({"allocations": f"The {slot.start_time:%H:%M} slot is listed twice."})
                seen.add(slot.pk)
                if day == today and slot.start_time <= timezone.localtime().time():
                    raise ValidationError({"allocations": f"The {slot.start_time:%H:%M} slot has already started."})
                items = alloc.get("items")
                if items:
                    if any(i["ticket_type"].museum_id != museum.id for i in items):
                        raise ValidationError({"allocations": "Ticket type does not belong to the museum."})
                else:
                    items = [{"ticket_type": default_ticket, "quantity": alloc.get("participants") or 0}]
                if sum(i["quantity"] for i in items) + alloc["escorts"] == 0:
                    continue  # empty row in the editor
                if slot.pk in slot_closed:
                    raise ValidationError({"allocations": f"The {slot.start_time:%H:%M} slot is closed on "
                                                          f"{day:%d %b %Y}: {slot_closed[slot.pk]}"})
                allocations.append({"slot": slot, "items": items, "escorts": alloc["escorts"]})
            if not allocations:
                raise ValidationError({"allocations": "Allocate the group to at least one slot."})

            pay_by_day = data.get("pay_by") or min(today + datetime.timedelta(days=PAY_BY_DEFAULT_DAYS), day)
            if pay_by_day < today or pay_by_day > day:
                raise ValidationError({"pay_by": "The pay-by date must be between today and the visit date."})
            end_of_day = timezone.make_aware(datetime.datetime.combine(pay_by_day, datetime.time(23, 59, 59)))
            pay_by = min(end_of_day, services.group_request_pay_by_limit(day, [a["slot"] for a in allocations]))
            if pay_by <= timezone.now():
                raise ValidationError({"pay_by": "The pay-by time has already passed."})

            pct = data.get("discount_percent")
            if pct is None:
                pct = services.group_discount_percent(museum, group_request.group_type)
            bookings = services.create_group_request_bookings(
                group_request=group_request, visit_date=day, allocations=allocations,
                discount_percent=pct, pay_by=pay_by,
            )
            group_request.status = GroupRequest.Status.APPROVED
            group_request.approved_date = day
            group_request.quoted_total = sum(b.total_amount for b in bookings)
            group_request.discount_percent = pct
            group_request.payment_mode = data["payment_mode"]
            group_request.pay_by = pay_by
            group_request.decided_by = request.user
            group_request.decided_at = timezone.now()
            if data.get("staff_notes") is not None:
                group_request.staff_notes = data["staff_notes"]
            group_request.save()
            for booking in bookings:
                if booking.total_amount == 0:  # e.g. all free tickets: nothing to pay
                    services.confirm_payment(booking, Booking.PaymentMethod.FREE)
            services.sync_group_request_status(group_request)
        return Response(self.out(group_request))

    @action(detail=True, methods=["post"], permission_classes=[IsPanelUser])
    def decline(self, request, pk=None):
        serializer = DeclineSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        with transaction.atomic():
            group_request = self.locked()
            if group_request.status not in (*GroupRequest.OPEN, GroupRequest.Status.APPROVED):
                raise ValidationError(f"This request is {group_request.get_status_display().lower()} and can't be declined.")
            if group_request.bookings.filter(status__in=services.PAID_STATUSES).exists():
                raise ValidationError("Some bookings of this request are already paid. Cancel them from Bookings first.")
            self._release_bookings(group_request)
            group_request.status = GroupRequest.Status.DECLINED
            group_request.staff_notes = serializer.validated_data["reason"]
            group_request.decided_by = request.user
            group_request.decided_at = timezone.now()
            group_request.save()
        return Response(self.out(group_request))

    @action(detail=True, methods=["post"], permission_classes=[IsPanelUser], url_path="mark-paid")
    def mark_paid(self, request, pk=None):
        """Bank transfer / invoice payment received: confirm all unpaid bookings of the request."""
        serializer = MarkPaidSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        ref = serializer.validated_data.get("payment_id") or serializer.validated_data.get("reference") or ""
        with transaction.atomic():
            group_request = self.locked()
            if group_request.status not in (GroupRequest.Status.APPROVED, GroupRequest.Status.EXPIRED):
                raise ValidationError(f"This request is {group_request.get_status_display().lower()}, nothing to mark paid.")
            services.mark_group_request_paid(group_request, ref.strip())
        return Response(self.out(group_request))
