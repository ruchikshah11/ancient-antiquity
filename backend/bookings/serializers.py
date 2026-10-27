import datetime

from django.conf import settings
from django.utils import timezone
from rest_framework import serializers

from museums.models import Museum, TicketType, TimeSlot

from .models import Booking, BookingAddOn, BookingItem
from .services import closure_error, max_free_escorts


class BookingItemSerializer(serializers.ModelSerializer):
    line_total = serializers.DecimalField(max_digits=10, decimal_places=2, read_only=True)

    class Meta:
        model = BookingItem
        fields = ("ticket_name", "quantity", "unit_price", "line_total")


class BookingAddOnSerializer(serializers.ModelSerializer):
    line_total = serializers.DecimalField(max_digits=10, decimal_places=2, read_only=True)
    icon = serializers.SerializerMethodField()

    class Meta:
        model = BookingAddOn
        fields = ("addon", "name", "kind", "icon", "quantity", "unit_price", "line_total")

    def get_icon(self, obj):
        from addons.models import AddOn

        return AddOn.ICONS.get(obj.kind, "plus-circle")


class BookingSerializer(serializers.ModelSerializer):
    items = BookingItemSerializer(many=True, read_only=True)
    museum_name = serializers.CharField(source="museum.name", read_only=True)
    museum_slug = serializers.CharField(source="museum.slug", read_only=True)
    museum_address = serializers.CharField(source="museum.address", read_only=True)
    museum_image = serializers.CharField(source="museum.image_url", read_only=True)
    city_name = serializers.CharField(source="museum.city.name", read_only=True)
    state_name = serializers.CharField(source="museum.city.state.name", read_only=True)
    # Entry slot times, or the event session's times for event tickets (slot is empty then).
    slot_start = serializers.TimeField(source="slot_start_time", read_only=True)
    slot_end = serializers.TimeField(source="slot_end_time", read_only=True)
    is_event = serializers.BooleanField(read_only=True)
    event_title = serializers.CharField(read_only=True)
    event_slug = serializers.SerializerMethodField()
    user_email = serializers.CharField(source="user.email", read_only=True)
    status_label = serializers.CharField(source="get_status_display", read_only=True)
    hold_expires_at = serializers.DateTimeField(read_only=True)
    can_cancel = serializers.BooleanField(read_only=True)
    sold_by_email = serializers.CharField(source="sold_by.email", read_only=True, default=None)
    group_type_label = serializers.CharField(source="get_group_type_display", read_only=True)
    subtotal_amount = serializers.SerializerMethodField()
    remaining_to_enter = serializers.IntegerField(read_only=True)
    refundable_amount = serializers.DecimalField(max_digits=10, decimal_places=2, read_only=True)
    refund_status_label = serializers.CharField(source="get_refund_status_display", read_only=True)

    promo_code_text = serializers.CharField(source="promo_code.code", read_only=True, default=None)
    voucher_code = serializers.SerializerMethodField()
    addons = BookingAddOnSerializer(many=True, read_only=True)
    # "2 x Audio guide, 1 x Camera permit": for the gate screens and anything showing a one-line summary.
    addons_summary = serializers.CharField(read_only=True)
    membership_card = serializers.CharField(source="membership.card_number", read_only=True, default=None)

    def get_subtotal_amount(self, obj):
        """Entry tickets before discounts (add-ons are listed separately in addons_amount)."""
        return str(obj.tickets_amount)

    def get_event_slug(self, obj):
        return obj.event_session.event.slug if obj.event_session_id else None

    def get_voucher_code(self, obj):
        if not obj.voucher_amount:
            return None  # no query for the usual case
        redemption = obj.voucher_redemptions.select_related("voucher").order_by("-created_at").first()
        return redemption.voucher.code if redemption else None

    class Meta:
        model = Booking
        fields = (
            "reference", "status", "status_label", "museum_name", "museum_slug",
            "museum_address", "museum_image", "city_name", "state_name", "visit_date",
            "slot_start", "slot_end", "total_visitors", "total_amount", "items",
            "visitor_name", "visitor_email", "visitor_phone", "payment_method",
            "payment_id", "created_at", "paid_at", "cancelled_at", "checked_in_at",
            "hold_expires_at", "can_cancel", "user_email", "channel", "sold_by_email",
            "is_group", "group_type", "group_type_label", "organisation_name", "escort_count",
            "subtotal_amount", "discount_amount", "visitors_arrived", "remaining_to_enter",
            "gateway", "refund_amount", "refund_status", "refund_status_label", "refund_id", "refundable_amount",
            "pay_by", "group_request",
            "promo_code", "promo_code_text", "promo_discount", "voucher_amount", "voucher_code",
            "is_event", "event_session", "event_title", "event_slug",
            "addons", "addons_amount", "addons_summary", "membership_discount", "membership_card",
        )


class BookingItemInput(serializers.Serializer):
    ticket_type = serializers.PrimaryKeyRelatedField(queryset=TicketType.objects.filter(is_active=True))
    quantity = serializers.IntegerField(min_value=0, max_value=settings.GROUP_MAX_SIZE)  # booking totals are checked per booking type


class BookingCreateSerializer(serializers.Serializer):
    # Which Admin -> Settings / place switch applies (None = never blocked, e.g. counter sales).
    booking_kind = "individual"
    museum = serializers.SlugRelatedField(slug_field="slug", queryset=Museum.objects.filter(is_active=True))
    slot = serializers.PrimaryKeyRelatedField(queryset=TimeSlot.objects.filter(is_active=True))
    visit_date = serializers.DateField()
    items = BookingItemInput(many=True)
    visitor_name = serializers.CharField(max_length=120)
    visitor_email = serializers.EmailField()
    visitor_phone = serializers.RegexField(r"^\+?[0-9]{10,13}$", error_messages={"invalid": "Enter a valid phone number."})

    def validate(self, attrs):
        museum, slot, day = attrs["museum"], attrs["slot"], attrs["visit_date"]
        today = timezone.localdate()
        if self.booking_kind:
            from museums.groups import block_reason

            reason = block_reason(museum, self.booking_kind)
            if reason:
                raise serializers.ValidationError({"museum": reason})

        if slot.museum_id != museum.id:
            raise serializers.ValidationError({"slot": "This slot does not belong to the museum."})
        if day < today:
            raise serializers.ValidationError({"visit_date": "Visit date is in the past."})
        if day > today + datetime.timedelta(days=settings.BOOKING_WINDOW_DAYS):
            raise serializers.ValidationError(
                {"visit_date": f"Bookings open {settings.BOOKING_WINDOW_DAYS} days in advance."}
            )
        if museum.is_closed_on(day):
            raise serializers.ValidationError({"visit_date": f"{museum.name} is closed on this day."})
        closed = closure_error(museum, slot, day)  # closures calendar: holidays, maintenance, partial closures
        if closed:
            raise serializers.ValidationError(closed)
        self.validate_slot_time(slot, day, today)
        attrs["items"] = self.validate_ticket_items(attrs["items"], museum, self.max_tickets)
        return attrs

    max_tickets = settings.MAX_TICKETS_PER_BOOKING

    def validate_slot_time(self, slot, day, today):
        if day == today and slot.start_time <= timezone.localtime().time():
            raise serializers.ValidationError({"slot": "This slot has already started."})

    @staticmethod
    def validate_ticket_items(items, museum, max_tickets):
        items = [i for i in items if i["quantity"] > 0]
        if not items:
            raise serializers.ValidationError({"items": "Select at least one ticket."})
        if any(i["ticket_type"].museum_id != museum.id for i in items):
            raise serializers.ValidationError({"items": "Ticket type does not belong to the museum."})
        if sum(i["quantity"] for i in items) > max_tickets:
            more = " For larger parties use a group booking." if max_tickets == settings.MAX_TICKETS_PER_BOOKING else ""
            raise serializers.ValidationError({"items": f"Maximum {max_tickets} tickets per booking.{more}"})
        return items


class GroupBookingSerializer(BookingCreateSerializer):
    """21-60 paying participants, a group type and organisation; schools/colleges may add free escorts."""

    max_tickets = settings.GROUP_MAX_SIZE
    booking_kind = "instant"
    group_type = serializers.ChoiceField(choices=Booking.GroupType.choices)
    organisation_name = serializers.CharField(max_length=150)
    escort_count = serializers.IntegerField(min_value=0, default=0)

    def validate(self, attrs):
        attrs = super().validate(attrs)
        museum = attrs["museum"]
        participants = sum(i["quantity"] for i in attrs["items"])
        if participants < settings.GROUP_MIN_SIZE:
            raise serializers.ValidationError(
                {"items": f"Group bookings start at {settings.GROUP_MIN_SIZE} people. Smaller parties can book normally."}
            )
        allowed = max_free_escorts(attrs["group_type"], participants)
        if attrs["escort_count"] > allowed:
            msg = (f"Up to {allowed} free escort(s) for {participants} students."
                   if allowed else "Free escorts are only for school and college groups.")
            raise serializers.ValidationError({"escort_count": msg})
        return attrs


class CounterSaleSerializer(BookingCreateSerializer):
    """Walk-in ticket sold by staff at the museum: today only, paid on the spot."""

    booking_kind = None  # staff at the gate decide; the online switches don't apply

    visit_date = serializers.DateField(required=False)
    visitor_name = serializers.CharField(max_length=120, required=False, default="Walk-in visitor")
    visitor_email = serializers.EmailField(required=False, allow_blank=True, default="")
    visitor_phone = serializers.RegexField(
        r"^(\+?[0-9]{10,13})?$", required=False, allow_blank=True, default="",
        error_messages={"invalid": "Enter a valid phone number."},
    )
    payment_method = serializers.ChoiceField(
        choices=[Booking.PaymentMethod.CASH, Booking.PaymentMethod.UPI, Booking.PaymentMethod.CARD]
    )
    check_in = serializers.BooleanField(default=True)

    def validate(self, attrs):
        today = timezone.localdate()
        attrs["visit_date"] = attrs.get("visit_date") or today
        if attrs["visit_date"] != today:
            raise serializers.ValidationError({"visit_date": "Counter tickets are for today's visit only."})
        return super().validate(attrs)

    def validate_slot_time(self, slot, day, today):
        # Walk-ins may join a slot that is already running, just not one that has ended.
        if slot.end_time <= timezone.localtime().time():
            raise serializers.ValidationError({"slot": "This slot has already ended."})


class CheckinSyncEntry(serializers.Serializer):
    reference = serializers.CharField(max_length=12)
    checked_in_at = serializers.DateTimeField()
    arrived = serializers.IntegerField(min_value=1, required=False)  # group part-arrival; omitted = everyone
    scan_id = serializers.CharField(max_length=40, required=False)  # makes re-sending the same scan harmless


class CheckinSyncSerializer(serializers.Serializer):
    museum = serializers.SlugRelatedField(slug_field="slug", queryset=Museum.objects.all())
    entries = CheckinSyncEntry(many=True)


class AddOnChoice(serializers.Serializer):
    addon = serializers.IntegerField(min_value=1)
    quantity = serializers.IntegerField(min_value=0, max_value=100)


class BookingAddOnsSerializer(serializers.Serializer):
    """POST /bookings/<reference>/addons/: the full new selection (an empty list removes every add-on)."""

    items = AddOnChoice(many=True, allow_empty=True)


class RazorpayPaySerializer(serializers.Serializer):
    razorpay_order_id = serializers.CharField(max_length=40)
    razorpay_payment_id = serializers.CharField(max_length=40)
    razorpay_signature = serializers.CharField(max_length=128)


class PaySerializer(serializers.Serializer):
    method = serializers.ChoiceField(
        choices=[Booking.PaymentMethod.UPI, Booking.PaymentMethod.CARD, Booking.PaymentMethod.NETBANKING]
    )
