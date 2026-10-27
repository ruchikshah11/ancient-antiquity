import datetime

from rest_framework import serializers

from bookings.services import effective_price
from museums.models import Museum

from .geo import city_centroids, coordinates, sized_image, starting_price
from .models import MAX_TRIP_DAYS, Trip, TripStop


class StopMuseumSerializer(serializers.ModelSerializer):
    """What a trip stop needs to show: timings, closed day, position, price."""

    city_name = serializers.CharField(source="city.name", read_only=True)
    state_name = serializers.CharField(source="city.state.name", read_only=True)
    image_url = serializers.SerializerMethodField()
    starting_price = serializers.SerializerMethodField()
    lat = serializers.SerializerMethodField()
    lng = serializers.SerializerMethodField()
    approximate = serializers.SerializerMethodField()

    class Meta:
        model = Museum
        fields = (
            "id", "slug", "name", "place_type", "city_name", "state_name", "image_url",
            "opening_time", "closing_time", "closed_weekday", "starting_price", "is_active",
            "lat", "lng", "approximate",
        )

    def _pos(self, obj):
        return coordinates(obj, self.context.get("centroids", {}))

    def get_image_url(self, obj):
        return sized_image(obj.image_url)

    def get_starting_price(self, obj):
        price = starting_price(obj)
        return None if price is None else str(price)

    def get_lat(self, obj):
        pos = self._pos(obj)
        return pos[0] if pos else None

    def get_lng(self, obj):
        pos = self._pos(obj)
        return pos[1] if pos else None

    def get_approximate(self, obj):
        pos = self._pos(obj)
        return pos[2] if pos else None


def stop_date(stop, trip=None):
    """Planned visit date of a stop: the trip's start date + (day - 1), or None for an undated trip."""
    trip = trip or stop.trip
    if not trip.start_date:
        return None
    return trip.start_date + datetime.timedelta(days=stop.day - 1)


def nearest_slot(museum, planned_time):
    """Id of the active slot covering planned_time, else the one starting closest to it (None without a time)."""
    if planned_time is None:
        return None
    slots = [s for s in museum.slots.all() if s.is_active]
    if not slots:
        return None
    for s in slots:
        if s.start_time <= planned_time < s.end_time:
            return s.id
    minutes = lambda t: t.hour * 60 + t.minute  # noqa: E731
    return min(slots, key=lambda s: (abs(minutes(s.start_time) - minutes(planned_time)), s.start_time)).id


def price_on(museum, day):
    """Like starting_price, but each ticket at its effective price on `day` (weekend / season rules)."""
    rules = sorted((r for r in museum.price_rules.all() if r.is_active), key=lambda r: (-r.priority, -r.id))
    prices = [effective_price(t, day, rules)[0] for t in museum.ticket_types.all() if t.is_active]
    if not prices:
        return None
    paid = [p for p in prices if p > 0]
    return min(paid) if paid else 0


class TripStopSerializer(serializers.ModelSerializer):
    museum = serializers.SlugRelatedField(
        slug_field="slug", queryset=Museum.objects.filter(is_active=True), write_only=True
    )
    place = StopMuseumSerializer(source="museum", read_only=True)
    visit_date = serializers.SerializerMethodField()
    slot_id = serializers.SerializerMethodField()
    price_on_date = serializers.SerializerMethodField()

    class Meta:
        model = TripStop
        fields = ("id", "museum", "place", "day", "order", "planned_time", "notes", "visit_date", "slot_id",
                  "price_on_date")
        read_only_fields = ("id", "order")

    def _date(self, obj):
        return stop_date(obj, self.context.get("trip"))

    def get_visit_date(self, obj):
        return self._date(obj)

    def get_slot_id(self, obj):
        """Slot nearest the planned time, so "Book" can preselect it (only for dated stops)."""
        return nearest_slot(obj.museum, obj.planned_time) if self._date(obj) else None

    def get_price_on_date(self, obj):
        day = self._date(obj)
        price = price_on(obj.museum, day) if day else None
        return None if price is None else str(price)

    def get_fields(self):
        fields = super().get_fields()
        if self.instance is not None and not isinstance(self.instance, (list, tuple)):
            fields["museum"].required = False
        return fields

    def validate_day(self, value):
        trip = self.context.get("trip")
        limit = (trip.day_count if trip else None) or MAX_TRIP_DAYS
        if not 1 <= value <= limit:
            raise serializers.ValidationError(f"Day must be between 1 and {limit}.")
        return value


class TripListSerializer(serializers.ModelSerializer):
    stop_count = serializers.SerializerMethodField()
    day_count = serializers.IntegerField(read_only=True)

    class Meta:
        model = Trip
        fields = ("id", "title", "start_date", "end_date", "notes", "day_count", "stop_count", "created_at", "updated_at")
        read_only_fields = ("id", "created_at", "updated_at")

    def get_stop_count(self, obj):
        count = getattr(obj, "stop_count", None)
        return obj.stops.count() if count is None else count

    def validate_title(self, value):
        value = value.strip()
        if not value:
            raise serializers.ValidationError("Give the trip a name.")
        return value

    def validate(self, attrs):
        start = attrs.get("start_date", getattr(self.instance, "start_date", None))
        end = attrs.get("end_date", getattr(self.instance, "end_date", None))
        if start and end:
            if end < start:
                raise serializers.ValidationError({"end_date": "End date must be on or after the start date."})
            if (end - start).days + 1 > MAX_TRIP_DAYS:
                raise serializers.ValidationError({"end_date": f"A trip can be at most {MAX_TRIP_DAYS} days long."})
        return attrs


class TripDetailSerializer(TripListSerializer):
    stops = serializers.SerializerMethodField()

    class Meta(TripListSerializer.Meta):
        fields = TripListSerializer.Meta.fields + ("stops",)

    def get_stops(self, obj):
        stops = list(obj.stops.select_related("museum__city__state").prefetch_related(
            "museum__ticket_types", "museum__slots", "museum__price_rules"))
        return serialize_stops(stops, {**self.context, "trip": obj})


def serialize_stops(stops, context, many=True):
    """Stops with place details; places without their own pin get their city's centre."""
    items = stops if many else [stops]
    centroids = city_centroids({s.museum.city_id for s in items if s.museum.latitude is None or s.museum.longitude is None})
    return TripStopSerializer(stops, many=many, context={**context, "centroids": centroids}).data
