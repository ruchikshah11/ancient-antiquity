import datetime

from django.conf import settings
from django.utils import timezone
from rest_framework import serializers

from museums.models import Museum, TimeSlot

from .models import Event, EventPrice, EventSession, WaitlistEntry


# --- Public ----------------------------------------------------------------------------------------------

class EventPriceSerializer(serializers.ModelSerializer):
    class Meta:
        model = EventPrice
        fields = ("id", "name", "price", "sort")


class EventListSerializer(serializers.ModelSerializer):
    kind_label = serializers.CharField(source="get_kind_display", read_only=True)
    museum_slug = serializers.CharField(source="museum.slug", read_only=True)
    museum_name = serializers.CharField(source="museum.name", read_only=True)
    museum_image = serializers.CharField(source="museum.image_url", read_only=True)
    city_name = serializers.CharField(source="museum.city.name", read_only=True)
    state_name = serializers.CharField(source="museum.city.state.name", read_only=True)
    state_id = serializers.IntegerField(source="museum.city.state_id", read_only=True)
    from_price = serializers.SerializerMethodField()
    next_date = serializers.DateField(read_only=True, default=None)
    upcoming_sessions = serializers.IntegerField(read_only=True, default=0)

    class Meta:
        model = Event
        fields = (
            "id", "slug", "title", "kind", "kind_label", "description", "image_url", "language",
            "duration_minutes", "featured", "museum_slug", "museum_name", "museum_image", "city_name",
            "state_name", "state_id", "from_price", "next_date", "upcoming_sessions",
        )

    def get_from_price(self, obj):
        prices = [p.price for p in obj.prices.all()]
        return str(min(prices)) if prices else None


class EventDetailSerializer(EventListSerializer):
    prices = EventPriceSerializer(many=True, read_only=True)
    sessions = serializers.SerializerMethodField()

    class Meta(EventListSerializer.Meta):
        fields = EventListSerializer.Meta.fields + ("prices", "sessions")

    def get_sessions(self, obj):
        return self.context.get("sessions", [])


class EventBookingItemInput(serializers.Serializer):
    price = serializers.PrimaryKeyRelatedField(queryset=EventPrice.objects.all())
    quantity = serializers.IntegerField(min_value=0, max_value=settings.MAX_TICKETS_PER_BOOKING)


class EventBookingCreateSerializer(serializers.Serializer):
    session = serializers.PrimaryKeyRelatedField(queryset=EventSession.objects.select_related("event__museum"))
    items = EventBookingItemInput(many=True)
    visitor_name = serializers.CharField(max_length=120)
    visitor_email = serializers.EmailField()
    visitor_phone = serializers.RegexField(r"^\+?[0-9]{10,13}$", error_messages={"invalid": "Enter a valid phone number."})

    def validate(self, attrs):
        from museums.groups import block_reason

        reason = block_reason(None, "events")
        if reason:
            raise serializers.ValidationError({"session": reason})
        attrs["items"] = [i for i in attrs["items"] if i["quantity"] > 0]
        if not attrs["items"]:
            raise serializers.ValidationError({"items": "Select at least one ticket."})
        return attrs


# --- Waitlist --------------------------------------------------------------------------------------------

class WaitlistEntrySerializer(serializers.ModelSerializer):
    status_label = serializers.CharField(source="get_status_display", read_only=True)
    museum_slug = serializers.CharField(source="museum.slug", read_only=True)
    museum_name = serializers.CharField(source="museum.name", read_only=True)
    start_time = serializers.SerializerMethodField()
    end_time = serializers.SerializerMethodField()
    event_title = serializers.SerializerMethodField()
    event_slug = serializers.SerializerMethodField()

    class Meta:
        model = WaitlistEntry
        fields = (
            "id", "museum_slug", "museum_name", "slot", "event_session", "event_title", "event_slug",
            "visit_date", "start_time", "end_time", "quantity", "status", "status_label", "notify_channels",
            "created_at", "notified_at",
        )

    def _times(self, obj):
        src = obj.event_session if obj.event_session_id else obj.slot
        return (src.start_time, src.end_time) if src else (None, None)

    def get_start_time(self, obj):
        t = self._times(obj)[0]
        return t.strftime("%H:%M:%S") if t else None

    def get_end_time(self, obj):
        t = self._times(obj)[1]
        return t.strftime("%H:%M:%S") if t else None

    def get_event_title(self, obj):
        return obj.event_session.event.title if obj.event_session_id else ""

    def get_event_slug(self, obj):
        return obj.event_session.event.slug if obj.event_session_id else None


class WaitlistCreateSerializer(serializers.Serializer):
    museum = serializers.SlugRelatedField(
        slug_field="slug", queryset=Museum.objects.filter(is_active=True), required=False
    )
    slot = serializers.PrimaryKeyRelatedField(queryset=TimeSlot.objects.filter(is_active=True), required=False)
    event_session = serializers.PrimaryKeyRelatedField(
        queryset=EventSession.objects.filter(is_active=True).select_related("event__museum"), required=False
    )
    visit_date = serializers.DateField(required=False)
    quantity = serializers.IntegerField(min_value=1, max_value=settings.MAX_TICKETS_PER_BOOKING)
    notify_channels = serializers.ListField(
        child=serializers.ChoiceField(choices=WaitlistEntry.CHANNELS), required=False, default=list
    )

    def validate(self, attrs):
        slot, session = attrs.get("slot"), attrs.get("event_session")
        today = timezone.localdate()
        if bool(slot) == bool(session):
            raise serializers.ValidationError("Choose either a time slot or an event session.")
        if session:
            attrs["museum"] = session.event.museum
            attrs["visit_date"] = session.date
            if session.starts_at <= timezone.now() or not session.event.is_active:
                raise serializers.ValidationError({"event_session": "This session is no longer on sale."})
        else:
            museum, day = attrs.get("museum"), attrs.get("visit_date")
            if not museum or not day:
                raise serializers.ValidationError("Pass the place and the visit date with the slot.")
            if slot.museum_id != museum.id:
                raise serializers.ValidationError({"slot": "This slot does not belong to the place."})
            if day < today or day > today + datetime.timedelta(days=settings.BOOKING_WINDOW_DAYS):
                raise serializers.ValidationError({"visit_date": "Pick a date inside the booking window."})
            if day == today and slot.start_time <= timezone.localtime().time():
                raise serializers.ValidationError({"slot": "This slot has already started."})
        attrs["notify_channels"] = sorted(set(attrs.get("notify_channels") or []))
        return attrs


# --- Admin -----------------------------------------------------------------------------------------------

class EventAdminSerializer(serializers.ModelSerializer):
    museum = serializers.SlugRelatedField(slug_field="slug", queryset=Museum.objects.all())
    museum_name = serializers.CharField(source="museum.name", read_only=True)
    kind_label = serializers.CharField(source="get_kind_display", read_only=True)
    prices = EventPriceSerializer(many=True, read_only=True)
    sessions_count = serializers.IntegerField(read_only=True, default=0)
    upcoming_sessions = serializers.IntegerField(read_only=True, default=0)

    class Meta:
        model = Event
        fields = (
            "id", "museum", "museum_name", "title", "slug", "kind", "kind_label", "description", "image_url",
            "language", "duration_minutes", "is_active", "featured", "prices", "sessions_count",
            "upcoming_sessions", "created_at", "updated_at",
        )
        read_only_fields = ("slug", "created_at", "updated_at")


class EventSessionAdminSerializer(serializers.ModelSerializer):
    booked = serializers.IntegerField(read_only=True, default=0)
    waiting = serializers.IntegerField(read_only=True, default=0)

    class Meta:
        model = EventSession
        fields = ("id", "event", "date", "start_time", "end_time", "capacity", "is_active", "booked", "waiting")

    def validate(self, attrs):
        start = attrs.get("start_time", getattr(self.instance, "start_time", None))
        end = attrs.get("end_time", getattr(self.instance, "end_time", None))
        if start and end and end <= start:
            raise serializers.ValidationError({"end_time": "End time must be after the start time."})
        return attrs


class EventPriceAdminSerializer(serializers.ModelSerializer):
    class Meta:
        model = EventPrice
        fields = ("id", "event", "name", "price", "sort")


class GenerateSessionsSerializer(serializers.Serializer):
    """Create one session per day in a date range (optionally only on some weekdays, 0=Mon..6=Sun)."""

    start_date = serializers.DateField()
    end_date = serializers.DateField()
    start_time = serializers.TimeField()
    end_time = serializers.TimeField()
    capacity = serializers.IntegerField(min_value=1)
    weekdays = serializers.ListField(child=serializers.IntegerField(min_value=0, max_value=6), required=False, default=list)

    def validate(self, attrs):
        if attrs["end_date"] < attrs["start_date"]:
            raise serializers.ValidationError({"end_date": "End date is before the start date."})
        if (attrs["end_date"] - attrs["start_date"]).days > 366:
            raise serializers.ValidationError({"end_date": "Generate at most one year at a time."})
        if attrs["end_time"] <= attrs["start_time"]:
            raise serializers.ValidationError({"end_time": "End time must be after the start time."})
        return attrs
