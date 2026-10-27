import datetime

from django.conf import settings
from django.utils import timezone
from rest_framework import serializers

from bookings.models import Booking
from bookings.serializers import BookingSerializer
from bookings.services import max_free_escorts
from museums.models import Museum, TicketType, TimeSlot

from .models import GroupRequest
from .pricing import closed_message

MAX_PARTICIPANTS = 1000
MIN_LEAD_DAYS = getattr(settings, "GROUP_REQUEST_MIN_LEAD_DAYS", 3)  # staff need time to review and plan


class GroupRequestSerializer(serializers.ModelSerializer):
    reference = serializers.CharField(read_only=True)
    museum_name = serializers.CharField(source="museum.name", read_only=True)
    museum_slug = serializers.CharField(source="museum.slug", read_only=True)
    city_name = serializers.CharField(source="museum.city.name", read_only=True)
    status_label = serializers.CharField(source="get_status_display", read_only=True)
    group_type_label = serializers.CharField(source="get_group_type_display", read_only=True)
    preferred_time_label = serializers.CharField(source="get_preferred_time_display", read_only=True)
    payment_mode_label = serializers.CharField(source="get_payment_mode_display", read_only=True)
    requester_email = serializers.CharField(source="requester.email", read_only=True)
    decided_by_email = serializers.CharField(source="decided_by.email", read_only=True, default=None)
    bookings = BookingSerializer(many=True, read_only=True)
    can_cancel = serializers.SerializerMethodField()

    class Meta:
        model = GroupRequest
        fields = (
            "id", "reference", "museum_name", "museum_slug", "city_name", "preferred_date", "alternative_date",
            "preferred_time", "preferred_time_label", "group_type", "group_type_label", "organisation_name",
            "contact_name", "contact_email", "contact_phone", "participants", "escorts", "needs_guide", "notes",
            "status", "status_label", "staff_notes", "quoted_total", "discount_percent", "approved_date",
            "decided_by_email", "decided_at", "payment_mode", "payment_mode_label", "pay_by", "requester_email",
            "created_at", "updated_at", "bookings", "can_cancel",
        )

    def get_can_cancel(self, obj):
        return can_cancel(obj)


def can_cancel(obj):
    if obj.status in GroupRequest.OPEN:
        return True
    if obj.status == GroupRequest.Status.APPROVED:
        return not any(b.status in (Booking.Status.CONFIRMED, Booking.Status.CHECKED_IN) for b in obj.bookings.all())
    return False


def check_visit_day(museum, day, field):
    today = timezone.localdate()
    if day < today + datetime.timedelta(days=MIN_LEAD_DAYS):
        raise serializers.ValidationError(
            {field: f"Large group visits must be requested at least {MIN_LEAD_DAYS} days ahead."}
        )
    if day > today + datetime.timedelta(days=settings.BOOKING_WINDOW_DAYS):
        raise serializers.ValidationError({field: f"Visits can be requested up to {settings.BOOKING_WINDOW_DAYS} days ahead."})
    closed = closed_message(museum, day)  # weekly closed day or a holiday / closure in the calendar
    if closed:
        raise serializers.ValidationError({field: closed})


class GroupRequestCreateSerializer(serializers.ModelSerializer):
    museum = serializers.SlugRelatedField(slug_field="slug", queryset=Museum.objects.filter(is_active=True))
    participants = serializers.IntegerField(min_value=settings.GROUP_MAX_SIZE + 1, max_value=MAX_PARTICIPANTS, error_messages={
        "min_value": f"Requests are for groups of more than {settings.GROUP_MAX_SIZE}. Smaller groups can book instantly.",
        "max_value": f"We can take requests for up to {MAX_PARTICIPANTS} people. Please contact us for larger events.",
    })
    escorts = serializers.IntegerField(min_value=0, default=0)
    contact_phone = serializers.RegexField(r"^\+?[0-9]{10,13}$", error_messages={"invalid": "Enter a valid phone number."})

    class Meta:
        model = GroupRequest
        fields = (
            "museum", "preferred_date", "alternative_date", "preferred_time", "group_type", "organisation_name",
            "contact_name", "contact_email", "contact_phone", "participants", "escorts", "needs_guide", "notes",
        )

    def validate(self, attrs):
        museum = attrs["museum"]
        from museums.groups import group_block_reason

        reason = group_block_reason(museum, "request")
        if reason:
            raise serializers.ValidationError({"museum": reason})
        check_visit_day(museum, attrs["preferred_date"], "preferred_date")
        alt = attrs.get("alternative_date")
        if alt:
            if alt == attrs["preferred_date"]:
                raise serializers.ValidationError({"alternative_date": "Pick a different day from the preferred date."})
            check_visit_day(museum, alt, "alternative_date")
        allowed = max_free_escorts(attrs["group_type"], attrs["participants"])
        if attrs["escorts"] > allowed:
            msg = (f"Up to {allowed} free escort(s) for {attrs['participants']} students."
                   if allowed else "Free escorts are only for school and college groups.")
            raise serializers.ValidationError({"escorts": msg})
        return attrs


class AllocationItemInput(serializers.Serializer):
    ticket_type = serializers.PrimaryKeyRelatedField(queryset=TicketType.objects.filter(is_active=True))
    quantity = serializers.IntegerField(min_value=0, max_value=MAX_PARTICIPANTS)


class AllocationInput(serializers.Serializer):
    slot = serializers.PrimaryKeyRelatedField(queryset=TimeSlot.objects.filter(is_active=True))
    participants = serializers.IntegerField(min_value=0, max_value=MAX_PARTICIPANTS, required=False)
    escorts = serializers.IntegerField(min_value=0, default=0)
    items = AllocationItemInput(many=True, required=False)  # per-ticket split; default: all on ticket_type


class ApproveSerializer(serializers.Serializer):
    date = serializers.DateField()
    allocations = AllocationInput(many=True)
    ticket_type = serializers.PrimaryKeyRelatedField(queryset=TicketType.objects.filter(is_active=True), required=False)
    discount_percent = serializers.IntegerField(min_value=0, max_value=100, required=False)
    payment_mode = serializers.ChoiceField(choices=GroupRequest.PaymentMode.choices, default=GroupRequest.PaymentMode.INVOICE)
    pay_by = serializers.DateField(required=False, help_text="Last day to pay; default 7 days, never after the visit")
    staff_notes = serializers.CharField(required=False, allow_blank=True)


class DeclineSerializer(serializers.Serializer):
    reason = serializers.CharField(max_length=2000)


class MarkPaidSerializer(serializers.Serializer):
    payment_id = serializers.CharField(max_length=40, required=False, allow_blank=True)
    reference = serializers.CharField(max_length=40, required=False, allow_blank=True)


class QuoteSerializer(serializers.Serializer):
    """GET /group-requests/quote/: estimated price of a large group visit on a date."""

    museum = serializers.SlugRelatedField(slug_field="slug", queryset=Museum.objects.filter(is_active=True))
    date = serializers.DateField()
    participants = serializers.IntegerField(min_value=1, max_value=MAX_PARTICIPANTS)
    group_type = serializers.ChoiceField(choices=Booking.GroupType.choices)
    ticket_type = serializers.PrimaryKeyRelatedField(queryset=TicketType.objects.filter(is_active=True), required=False)
    discount_percent = serializers.IntegerField(min_value=0, max_value=100, required=False)

    def validate(self, attrs):
        ticket = attrs.get("ticket_type")
        if ticket and ticket.museum_id != attrs["museum"].id:
            raise serializers.ValidationError({"ticket_type": "Choose a ticket type of this place."})
        return attrs
