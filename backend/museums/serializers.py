from decimal import Decimal

from django.db import transaction
from django.db.models import ProtectedError
from django.utils import timezone
from rest_framework import serializers

from .models import (
    FACILITY_FLAGS, FACILITY_TEXTS, PHOTOGRAPHY_CHOICES, Category, City, Museum, MuseumImage, PlaceClosure, PriceRule,
    Review, ReviewPhoto, State, TicketType, TimeSlot,
)


class StateSerializer(serializers.ModelSerializer):
    museum_count = serializers.IntegerField(read_only=True)

    class Meta:
        model = State
        fields = ("id", "name", "code", "is_union_territory", "museum_count")


class CitySerializer(serializers.ModelSerializer):
    state_name = serializers.CharField(source="state.name", read_only=True)

    class Meta:
        model = City
        fields = ("id", "name", "state", "state_name")


class CategorySerializer(serializers.ModelSerializer):
    class Meta:
        model = Category
        fields = ("id", "name", "slug")


class TicketTypeSerializer(serializers.ModelSerializer):
    id = serializers.IntegerField(required=False)

    class Meta:
        model = TicketType
        fields = ("id", "name", "description", "price", "sort_order", "is_active")


class TimeSlotSerializer(serializers.ModelSerializer):
    id = serializers.IntegerField(required=False)

    class Meta:
        model = TimeSlot
        fields = ("id", "start_time", "end_time", "capacity", "is_active")

    def validate(self, attrs):
        if attrs["end_time"] <= attrs["start_time"]:
            raise serializers.ValidationError("Slot end time must be after start time.")
        return attrs


class ReviewPhotoSerializer(serializers.ModelSerializer):
    url = serializers.SerializerMethodField()
    status_label = serializers.CharField(source="get_status_display", read_only=True)

    class Meta:
        model = ReviewPhoto
        fields = ("id", "url", "status", "status_label", "created_at")
        read_only_fields = fields

    def get_url(self, obj):
        if not obj.image:
            return ""
        request = self.context.get("request")
        return request.build_absolute_uri(obj.image.url) if request else obj.image.url


class ReviewSerializer(serializers.ModelSerializer):
    user_name = serializers.SerializerMethodField()
    # Approved photos only; the owner's own review (context own_review=True) also lists pending ones.
    photos = serializers.SerializerMethodField()
    photo_statuses = (ReviewPhoto.Status.APPROVED,)
    # A JSON number (4.5), not the string "4.5" DRF uses for decimals by default.
    rating = serializers.DecimalField(
        max_digits=2, decimal_places=1, min_value=Decimal("0.5"), max_value=Decimal("5"), coerce_to_string=False,
    )
    comment = serializers.CharField(max_length=2000, required=False, allow_blank=True)
    # Whether the signed-in visitor marked this review helpful (context "voted_ids": ids they voted on).
    voted_by_me = serializers.SerializerMethodField()

    class Meta:
        model = Review
        fields = (
            "id", "rating", "title", "comment", "user_name", "photos", "helpful_count", "voted_by_me",
            "created_at", "updated_at",
        )
        read_only_fields = ("id", "user_name", "photos", "helpful_count", "voted_by_me", "created_at", "updated_at")

    def get_voted_by_me(self, obj):
        return obj.id in self.context.get("voted_ids", ())

    def validate_rating(self, value):
        if (value * 2) % 1:
            raise serializers.ValidationError("Use whole or half stars (for example 4 or 4.5).")
        return value

    def get_photos(self, obj):
        statuses = self.photo_statuses
        if self.context.get("own_review"):
            statuses = (ReviewPhoto.Status.APPROVED, ReviewPhoto.Status.PENDING)
        photos = [p for p in obj.photos.all() if p.status in statuses]
        return ReviewPhotoSerializer(photos, many=True, context=self.context).data

    def get_user_name(self, obj):
        # First name + initial only, so reviewers aren't fully identified publicly.
        first, last = obj.user.first_name.strip(), obj.user.last_name.strip()
        if first:
            return f"{first} {last[:1]}." if last else first
        return obj.user.email.split("@")[0][:3] + "…"


class AdminReviewSerializer(ReviewSerializer):
    photo_statuses = tuple(ReviewPhoto.Status.values)  # moderators see every photo
    # Moderators can hide or delete a review, never change what the visitor rated.
    rating = serializers.DecimalField(max_digits=2, decimal_places=1, coerce_to_string=False, read_only=True)
    museum_name = serializers.CharField(source="museum.name", read_only=True)
    museum_slug = serializers.CharField(source="museum.slug", read_only=True)
    user_email = serializers.CharField(source="user.email", read_only=True)

    class Meta(ReviewSerializer.Meta):
        fields = ReviewSerializer.Meta.fields + ("is_published", "museum_name", "museum_slug", "user_email")
        read_only_fields = ReviewSerializer.Meta.read_only_fields + ("rating", "title", "comment")


class MuseumImageSerializer(serializers.ModelSerializer):
    class Meta:
        model = MuseumImage
        fields = ("id", "url", "caption", "credit", "source_url")


class MuseumListSerializer(serializers.ModelSerializer):
    city_name = serializers.CharField(source="city.name", read_only=True)
    state_name = serializers.CharField(source="city.state.name", read_only=True)
    category_name = serializers.CharField(source="category.name", read_only=True, default=None)
    starting_price = serializers.SerializerMethodField()
    avg_rating = serializers.FloatField(read_only=True)
    review_count = serializers.IntegerField(read_only=True)
    info_verified_by_name = serializers.SerializerMethodField()

    class Meta:
        model = Museum
        fields = (
            "id", "name", "slug", "place_type", "tagline", "image_url", "city_name", "state_name",
            "category_name", "opening_time", "closing_time", "closed_weekday",
            "is_featured", "is_active", "starting_price", "avg_rating", "review_count",
            "info_verified", "info_verified_at", "info_verified_by_name", "allow_groups", "allow_individual",
        )
        read_only_fields = ("info_verified_at",)

    def to_representation(self, obj):
        data = super().to_representation(obj)
        if not data.get("image_url") and getattr(obj, "google_place_id", ""):
            add_google_photos(self, obj, data)
        return data

    def to_internal_value(self, data):
        # A Google photo link shown in the admin form must not be saved as the place's own photo.
        if "/google-photo/" in str(data.get("image_url") or ""):
            data = data.copy()  # works for JSON dicts and form QueryDicts
            data["image_url"] = self.instance.image_url if self.instance else ""
        return super().to_internal_value(data)

    def get_info_verified_by_name(self, obj):
        user = obj.info_verified_by
        if not user:
            return None
        return user.get_full_name().strip() or user.email

    def get_starting_price(self, obj):
        """Lowest paid ticket ("from ₹50"), so free child entry doesn't make a paid place look free."""
        prices = [t.price for t in obj.ticket_types.all() if t.is_active]
        if not prices:
            return None
        paid = [p for p in prices if p > 0]
        return min(paid) if paid else 0


def add_google_photos(serializer, obj, data):
    """Place without its own photo but matched on Google Maps: point the photo fields at our google-photo redirect.
    The detail view also lists the gallery with each photographer's name, as Google requires."""
    from django.urls import reverse

    from . import google_places

    if not google_places.enabled():
        return
    request = serializer.context.get("request")

    def link(i):
        path = reverse("museum-google-photo", kwargs={"slug": obj.slug, "index": i})
        return request.build_absolute_uri(path) if request else path

    data["image_url"] = link(0)
    data["photo_source"] = "google"
    if "images" not in data:
        data["image_credit"] = "Photo: Google Maps"
        return
    items = google_places.photos(obj.google_place_id)
    if not items:
        data["image_url"] = ""
        return
    data["image_credit"] = google_places.credit(items[0])
    data["image_source_url"] = items[0]["author_uri"]
    data["images"] = [
        {"id": -i, "url": link(i), "caption": obj.name, "credit": google_places.credit(item),
         "source_url": item["author_uri"]}
        for i, item in enumerate(items) if i
    ]


def guess_tour_kind(url):
    """Kind of a virtual tour link when the admin didn't pick one."""
    low = url.lower()
    if "youtube.com" in low or "youtu.be" in low or "vimeo.com" in low:
        return Museum.VirtualTourKind.VIDEO
    if ("google." in low and "/maps" in low) or "goo.gl/maps" in low or "maps.app.goo.gl" in low:
        return Museum.VirtualTourKind.STREET_VIEW
    if "artsandculture.google.com" in low:
        return Museum.VirtualTourKind.TOUR_360
    return Museum.VirtualTourKind.OTHER


class MuseumDetailSerializer(MuseumListSerializer):
    ticket_types = TicketTypeSerializer(many=True, required=False)
    slots = TimeSlotSerializer(many=True, required=False)
    state = serializers.IntegerField(source="city.state_id", read_only=True)
    images = MuseumImageSerializer(many=True, read_only=True)
    group_policy = serializers.SerializerMethodField()
    # Effective "open right now" flags (site-wide switches AND this place's allow_groups); allow_groups stays raw.
    individual_open = serializers.SerializerMethodField()
    groups_open = serializers.SerializerMethodField()
    group_requests_open = serializers.SerializerMethodField()
    school_trips_open = serializers.SerializerMethodField()
    groups_paused_message = serializers.SerializerMethodField()

    def get_individual_open(self, obj):
        from .groups import is_open

        return is_open(obj, "individual")

    def get_groups_open(self, obj):
        from .groups import groups_open

        return groups_open(obj, "instant")

    def get_group_requests_open(self, obj):
        from .groups import groups_open

        return groups_open(obj, "request")

    def get_school_trips_open(self, obj):
        from .groups import groups_open

        return groups_open(obj, "school")

    def get_groups_paused_message(self, obj):
        """Why online booking is limited here (empty when everything is open)."""
        from .groups import block_reason

        return block_reason(obj, "individual") or block_reason(obj, "instant") or ""

    def get_group_policy(self, obj):
        from django.conf import settings

        return {
            "min_size": settings.GROUP_MIN_SIZE,
            "max_size": settings.GROUP_MAX_SIZE,
            "escorts_per": settings.GROUP_ESCORTS_PER,
            "slot_share_percent": round(settings.GROUP_SLOT_SHARE * 100),
        }

    class Meta(MuseumListSerializer.Meta):
        fields = MuseumListSerializer.Meta.fields + (
            "image_credit", "image_source_url", "source_url", "images",
            "city", "state", "category", "description", "highlights", "address",
            "latitude", "longitude", "established_year", "managed_by",
            "contact_phone", "contact_email", "ticket_types", "slots",
            "allow_groups", "group_discount_percent", "school_discount_percent", "group_policy",
            "allow_individual", "individual_open", "groups_open", "group_requests_open", "school_trips_open",
            "groups_paused_message",
            "facilities", "virtual_tour_url", "virtual_tour_kind",
        )

    def validate_facilities(self, value):
        """Only known keys; flags are true/false, photography is a choice, the rest short texts."""
        if value in (None, ""):
            return {}
        if not isinstance(value, dict):
            raise serializers.ValidationError("Send an object of facility values.")
        clean, errors = {}, []
        for key, item in value.items():
            if item is None or item == "":
                continue
            if key in FACILITY_FLAGS:
                if not isinstance(item, bool):
                    errors.append(f"{key} must be true or false.")
                clean[key] = item
            elif key == "photography":
                if item not in PHOTOGRAPHY_CHOICES:
                    errors.append(f"photography must be one of {', '.join(PHOTOGRAPHY_CHOICES)}.")
                clean[key] = item
            elif key == "avg_visit_minutes":
                try:
                    minutes = int(item)
                except (TypeError, ValueError):
                    minutes = -1
                if not 0 < minutes <= 24 * 60:
                    errors.append("avg_visit_minutes must be a number of minutes (1-1440).")
                clean[key] = minutes
            elif key in FACILITY_TEXTS:
                if not isinstance(item, str):
                    errors.append(f"{key} must be text.")
                    continue
                limit = 1000 if key == "notes" else 200
                if len(item.strip()) > limit:
                    errors.append(f"{key} is longer than {limit} characters.")
                clean[key] = item.strip()
            else:
                errors.append(f"Unknown facility: {key}.")
        if errors:
            raise serializers.ValidationError(errors)
        return clean

    def validate(self, attrs):
        if "virtual_tour_url" in attrs:
            url = (attrs["virtual_tour_url"] or "").strip()
            attrs["virtual_tour_url"] = url
            if not url:
                attrs["virtual_tour_kind"] = ""
            elif not attrs.get("virtual_tour_kind"):
                same_link = self.instance is not None and self.instance.virtual_tour_url == url
                if not (same_link and self.instance.virtual_tour_kind):
                    attrs["virtual_tour_kind"] = guess_tour_kind(url)
        opening = attrs.get("opening_time", getattr(self.instance, "opening_time", None))
        closing = attrs.get("closing_time", getattr(self.instance, "closing_time", None))
        if opening and closing and closing <= opening:
            raise serializers.ValidationError({"closing_time": "Closing time must be after opening time."})
        return attrs

    def _stamp_verification(self, validated_data, instance=None):
        """Record who/when when info_verified is switched on; clear it when switched off."""
        if "info_verified" not in validated_data:
            return
        verified = validated_data["info_verified"]
        if verified and not (instance and instance.info_verified):
            request = self.context.get("request")
            validated_data["info_verified_at"] = timezone.now()
            validated_data["info_verified_by"] = request.user if request and request.user.is_authenticated else None
        elif not verified:
            validated_data["info_verified_at"] = None
            validated_data["info_verified_by"] = None

    @transaction.atomic
    def create(self, validated_data):
        tickets = validated_data.pop("ticket_types", [])
        slots = validated_data.pop("slots", [])
        self._stamp_verification(validated_data)
        museum = Museum.objects.create(**validated_data)
        self._sync(museum, TicketType, tickets)
        self._sync(museum, TimeSlot, slots)
        return museum

    @transaction.atomic
    def update(self, instance, validated_data):
        tickets = validated_data.pop("ticket_types", None)
        slots = validated_data.pop("slots", None)
        self._stamp_verification(validated_data, instance)
        for field, value in validated_data.items():
            setattr(instance, field, value)
        instance.save()
        if tickets is not None:
            self._sync(instance, TicketType, tickets)
        if slots is not None:
            self._sync(instance, TimeSlot, slots)
        return instance

    @staticmethod
    def _sync(museum, model, rows):
        """Upsert child rows; rows left out are deleted, or deactivated if bookings use them."""
        existing = {obj.id: obj for obj in model.objects.filter(museum=museum)}
        kept = set()
        for row in rows:
            row = dict(row)
            row_id = row.pop("id", None)
            if row_id in existing:
                obj = existing[row_id]
                for field, value in row.items():
                    setattr(obj, field, value)
                obj.save()
                kept.add(row_id)
            else:
                model.objects.create(museum=museum, **row)
        for obj_id, obj in existing.items():
            if obj_id in kept:
                continue
            try:
                obj.delete()
            except ProtectedError:
                obj.is_active = False
                obj.save(update_fields=["is_active"])


class ClosureSlotSerializer(serializers.ModelSerializer):
    class Meta:
        model = TimeSlot
        fields = ("id", "start_time", "end_time")


class PublicClosureSerializer(serializers.ModelSerializer):
    """Upcoming closures shown to visitors (date picker, timings)."""

    all_places = serializers.SerializerMethodField()
    slots = ClosureSlotSerializer(many=True, read_only=True)

    class Meta:
        model = PlaceClosure
        fields = ("id", "start_date", "end_date", "reason", "all_day", "slots", "all_places")

    def get_all_places(self, obj):
        return obj.museum_id is None


class PlaceClosureSerializer(PublicClosureSerializer):
    """Admin CRUD. museum = place slug, or null for a closure that applies to every place."""

    museum = serializers.SlugRelatedField(slug_field="slug", queryset=Museum.objects.all(), allow_null=True, required=False)
    museum_name = serializers.CharField(source="museum.name", read_only=True, default=None)
    slot_ids = serializers.PrimaryKeyRelatedField(
        source="slots", queryset=TimeSlot.objects.all(), many=True, required=False, write_only=True
    )
    created_by_email = serializers.CharField(source="created_by.email", read_only=True, default=None)

    class Meta(PublicClosureSerializer.Meta):
        fields = PublicClosureSerializer.Meta.fields + (
            "museum", "museum_name", "slot_ids", "created_by_email", "created_at",
        )
        read_only_fields = ("created_at",)

    def validate(self, attrs):
        get = lambda k, default=None: attrs.get(k, getattr(self.instance, k, default) if self.instance else default)  # noqa: E731
        start, end = get("start_date"), get("end_date")
        if start and end and end < start:
            raise serializers.ValidationError({"end_date": "The closure must end on or after its start date."})
        museum = get("museum")
        all_day = get("all_day", True)
        if "slots" in attrs:
            slots = attrs["slots"]
        else:
            slots = list(self.instance.slots.all()) if self.instance else []
        if all_day:
            attrs["slots"] = []
        else:
            if museum is None:
                raise serializers.ValidationError({"all_day": "A closure for all places must be for the whole day."})
            if not slots:
                raise serializers.ValidationError({"slot_ids": "Pick the slots that are closed, or close the whole day."})
            if any(s.museum_id != museum.id for s in slots):
                raise serializers.ValidationError({"slot_ids": "Those slots do not belong to this place."})
        return attrs


class PriceRuleSerializer(serializers.ModelSerializer):
    museum = serializers.SlugRelatedField(slug_field="slug", queryset=Museum.objects.all())
    ticket_type_name = serializers.CharField(source="ticket_type.name", read_only=True, default=None)

    class Meta:
        model = PriceRule
        fields = (
            "id", "museum", "name", "start_date", "end_date", "weekdays", "ticket_type", "ticket_type_name",
            "adjustment_type", "value", "priority", "is_active", "created_at",
        )
        read_only_fields = ("created_at",)

    def validate_weekdays(self, value):
        parts = [p.strip() for p in (value or "").split(",") if p.strip()]
        if any(p not in "0123456" or len(p) != 1 for p in parts):
            raise serializers.ValidationError("Use weekday numbers 0-6 (Monday = 0), separated by commas.")
        return ",".join(sorted(set(parts), key=int))

    def validate(self, attrs):
        get = lambda k: attrs.get(k, getattr(self.instance, k, None) if self.instance else None)  # noqa: E731
        start, end, museum, ticket = get("start_date"), get("end_date"), get("museum"), get("ticket_type")
        if start and end and end < start:
            raise serializers.ValidationError({"end_date": "The end date must be on or after the start date."})
        if ticket and museum and ticket.museum_id != museum.id:
            raise serializers.ValidationError({"ticket_type": "This ticket type belongs to another place."})
        kind, value = get("adjustment_type") or PriceRule.Adjustment.PERCENT, get("value")
        if value is not None:
            if kind == PriceRule.Adjustment.FIXED_PRICE and value < 0:
                raise serializers.ValidationError({"value": "A fixed price cannot be negative."})
            if kind == PriceRule.Adjustment.PERCENT and not -100 <= value <= 500:
                raise serializers.ValidationError({"value": "Percent change must be between -100 and +500."})
        return attrs


class SiteSettingsSerializer(serializers.ModelSerializer):
    updated_by_name = serializers.SerializerMethodField()

    class Meta:
        from .models import SiteSettings

        model = SiteSettings
        fields = ("individual_bookings_enabled", "group_bookings_enabled", "group_requests_enabled", "school_trips_enabled",
                  "events_enabled", "passes_enabled", "paused_message", "footer_brand", "footer_tagline",
                  "footer_copyright", "updated_at", "updated_by_name")
        read_only_fields = ("updated_at", "updated_by_name")

    def get_updated_by_name(self, obj):
        return obj.updated_by.get_full_name() or obj.updated_by.email if obj.updated_by else None
