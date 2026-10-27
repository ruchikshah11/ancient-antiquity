from rest_framework import serializers

from museums.models import Museum

from .models import AddOn


class AddOnSerializer(serializers.ModelSerializer):
    """Public view of an add-on (checkout, place page). `remaining` is set when a visit date is known."""

    kind_label = serializers.CharField(source="get_kind_display", read_only=True)
    per_label = serializers.CharField(source="get_per_display", read_only=True)
    icon = serializers.CharField(read_only=True)
    remaining = serializers.SerializerMethodField()

    class Meta:
        model = AddOn
        fields = ("id", "name", "description", "kind", "kind_label", "icon", "price", "per", "per_label",
                  "max_per_booking", "daily_stock", "remaining")

    def get_remaining(self, obj):
        return self.context.get("remaining", {}).get(obj.id)


class AddOnAdminSerializer(AddOnSerializer):
    museum = serializers.SlugRelatedField(slug_field="slug", queryset=Museum.objects.all())
    museum_name = serializers.CharField(source="museum.name", read_only=True)
    sold_count = serializers.SerializerMethodField()

    class Meta(AddOnSerializer.Meta):
        fields = AddOnSerializer.Meta.fields + (
            "museum", "museum_name", "is_active", "sort", "sold_count", "created_at", "updated_at",
        )
        read_only_fields = ("created_at", "updated_at")

    def get_sold_count(self, obj):
        """Units sold on paid bookings (all dates)."""
        from django.db.models import Sum

        from bookings.models import Booking

        return obj.booking_lines.filter(
            booking__status__in=[Booking.Status.CONFIRMED, Booking.Status.CHECKED_IN]
        ).aggregate(n=Sum("quantity"))["n"] or 0

    def validate_museum(self, museum):
        if self.instance is not None and museum.pk != self.instance.museum_id:
            raise serializers.ValidationError("An add-on cannot be moved to another place. Create a new one there.")
        return museum
