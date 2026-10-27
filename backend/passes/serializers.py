from django.db import transaction
from rest_framework import serializers

from museums.models import Museum

from .models import CATEGORIES, ComboPass, ComboPassSite, PassOrder


def site_data(museum):
    return {
        "slug": museum.slug,
        "name": museum.name,
        "place_type": museum.place_type,
        "city_name": museum.city.name,
        "state_name": museum.city.state.name,
        "image_url": museum.image_url,
    }


class PricesField(serializers.Field):
    def to_representation(self, obj):
        return {c: str(obj.price_for(c)) for c in CATEGORIES}


class ComboPassSerializer(serializers.ModelSerializer):
    prices = PricesField(source="*", read_only=True)
    from_price = serializers.DecimalField(max_digits=8, decimal_places=2, read_only=True)
    sites = serializers.SerializerMethodField()

    class Meta:
        model = ComboPass
        fields = ("id", "name", "slug", "description", "image_url", "validity_days", "prices", "from_price",
                  "featured", "sites")

    def get_sites(self, obj):
        return [site_data(m) for m in obj.ordered_sites()]


class ComboPassAdminSerializer(ComboPassSerializer):
    museum_slugs = serializers.ListField(
        child=serializers.SlugField(max_length=170), write_only=True, required=False, allow_empty=False,
        help_text="Included places in visiting order",
    )
    orders_count = serializers.SerializerMethodField()
    slug = serializers.SlugField(max_length=140, required=False, allow_blank=True)

    class Meta(ComboPassSerializer.Meta):
        fields = ComboPassSerializer.Meta.fields + (
            "price_indian", "price_foreign", "price_student", "price_child", "is_active", "museum_slugs",
            "orders_count", "created_at", "updated_at",
        )
        read_only_fields = ("created_at", "updated_at")

    def get_orders_count(self, obj):
        return obj.orders.filter(status=PassOrder.Status.CONFIRMED).count()

    def validate_museum_slugs(self, slugs):
        if len(set(slugs)) != len(slugs):
            raise serializers.ValidationError("A place is listed twice.")
        found = {m.slug: m for m in Museum.objects.filter(slug__in=slugs)}
        missing = [s for s in slugs if s not in found]
        if missing:
            raise serializers.ValidationError(f"Unknown place(s): {', '.join(missing)}")
        if len(slugs) < 2:
            raise serializers.ValidationError("A combo pass needs at least two places.")
        return [found[s] for s in slugs]

    def validate(self, attrs):
        if self.instance is None and "museum_slugs" not in attrs:
            raise serializers.ValidationError({"museum_slugs": "Choose the places included in the pass."})
        return attrs

    @transaction.atomic
    def create(self, validated_data):
        museums = validated_data.pop("museum_slugs")
        if not validated_data.get("slug"):
            validated_data.pop("slug", None)
        combo = ComboPass.objects.create(**validated_data)
        self._set_sites(combo, museums)
        return combo

    @transaction.atomic
    def update(self, instance, validated_data):
        museums = validated_data.pop("museum_slugs", None)
        if "slug" in validated_data and not validated_data["slug"]:
            validated_data.pop("slug")
        instance = super().update(instance, validated_data)
        if museums is not None:
            self._set_sites(instance, museums)
        return instance

    @staticmethod
    def _set_sites(combo, museums):
        combo.sites.all().delete()
        ComboPassSite.objects.bulk_create(
            [ComboPassSite(combo_pass=combo, museum=m, sort_order=i) for i, m in enumerate(museums)]
        )


class PassOrderCreateSerializer(serializers.Serializer):
    combo_pass = serializers.SlugRelatedField(slug_field="slug", queryset=ComboPass.objects.all())
    start_date = serializers.DateField()
    indian = serializers.IntegerField(min_value=0, max_value=50, default=0)
    foreign = serializers.IntegerField(min_value=0, max_value=50, default=0)
    student = serializers.IntegerField(min_value=0, max_value=50, default=0)
    child = serializers.IntegerField(min_value=0, max_value=50, default=0)
    visitor_name = serializers.CharField(max_length=120)
    visitor_email = serializers.EmailField(required=False, allow_blank=True, default="")
    visitor_phone = serializers.RegexField(r"^[0-9+\- ]{0,15}$", required=False, allow_blank=True, default="")

    def validate(self, attrs):
        from museums.groups import block_reason

        reason = block_reason(None, "passes")
        if reason:
            raise serializers.ValidationError({"combo_pass": reason})
        return attrs


class PassOrderSerializer(serializers.ModelSerializer):
    status_label = serializers.CharField(source="get_status_display", read_only=True)
    pass_slug = serializers.CharField(source="combo_pass.slug", read_only=True)
    pass_image = serializers.CharField(source="combo_pass.image_url", read_only=True)
    end_date = serializers.DateField(read_only=True)
    counts = serializers.SerializerMethodField()
    sites = serializers.SerializerMethodField()
    hold_expires_at = serializers.DateTimeField(read_only=True)
    refundable_amount = serializers.DecimalField(max_digits=10, decimal_places=2, read_only=True)
    can_cancel = serializers.BooleanField(read_only=True)
    refund_status_label = serializers.CharField(source="get_refund_status_display", read_only=True)
    user_email = serializers.CharField(source="user.email", read_only=True)

    class Meta:
        model = PassOrder
        fields = (
            "reference", "status", "status_label", "pass_name", "pass_slug", "pass_image", "start_date", "end_date",
            "validity_days", "counts", "unit_prices", "total_visitors", "total_amount", "visitor_name",
            "visitor_email", "visitor_phone", "payment_method", "payment_id", "gateway", "paid_at", "created_at",
            "cancelled_at", "hold_expires_at", "refund_amount", "refund_status", "refund_status_label",
            "refundable_amount", "can_cancel", "sites", "user_email",
        )

    def get_counts(self, obj):
        return {c: obj.count_for(c) for c in CATEGORIES}

    def get_sites(self, obj):
        visits = {v.museum_id: v for v in obj.visits.all()}
        out = []
        for m in obj.combo_pass.ordered_sites():
            v = visits.get(m.id)
            out.append({**site_data(m), "used": bool(v), "visited_at": v.visited_at if v else None})
        return out
