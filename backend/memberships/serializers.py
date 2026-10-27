from rest_framework import serializers

from museums.models import Museum

from .models import Membership, MembershipPlan


class MembershipPlanSerializer(serializers.ModelSerializer):
    """Public plan card. `places` is empty when the card works at every place."""

    places = serializers.SerializerMethodField()
    all_places = serializers.SerializerMethodField()
    benefit_percent = serializers.IntegerField(read_only=True)

    class Meta:
        model = MembershipPlan
        fields = ("id", "name", "slug", "description", "price", "duration_days", "discount_percent", "free_entry",
                  "benefit_percent", "max_visitors_per_booking", "places", "all_places")

    def get_places(self, obj):
        return [{"slug": m.slug, "name": m.name, "city_name": m.city.name} for m in obj.places.select_related("city")]

    def get_all_places(self, obj):
        return not obj.places.exists()


class MembershipPlanAdminSerializer(MembershipPlanSerializer):
    place_slugs = serializers.ListField(
        child=serializers.SlugField(max_length=170), write_only=True, required=False,
        help_text="Places where the card works (empty list = all places)",
    )
    slug = serializers.SlugField(max_length=120, required=False, allow_blank=True)
    active_members = serializers.SerializerMethodField()

    class Meta(MembershipPlanSerializer.Meta):
        fields = MembershipPlanSerializer.Meta.fields + (
            "is_active", "sort", "place_slugs", "active_members", "created_at", "updated_at",
        )
        read_only_fields = ("created_at", "updated_at")

    def get_active_members(self, obj):
        return obj.memberships.filter(status=Membership.Status.ACTIVE).count()

    def validate_place_slugs(self, slugs):
        found = {m.slug: m for m in Museum.objects.filter(slug__in=slugs)}
        missing = [s for s in slugs if s not in found]
        if missing:
            raise serializers.ValidationError(f"Unknown place(s): {', '.join(missing)}")
        return list(found.values())

    def validate(self, attrs):
        if "slug" in attrs and not attrs["slug"]:
            attrs.pop("slug")
        return attrs

    def create(self, validated_data):
        places = validated_data.pop("place_slugs", [])
        plan = MembershipPlan.objects.create(**validated_data)
        plan.places.set(places)
        return plan

    def update(self, instance, validated_data):
        places = validated_data.pop("place_slugs", None)
        instance = super().update(instance, validated_data)
        if places is not None:
            instance.places.set(places)
        return instance


class MembershipSerializer(serializers.ModelSerializer):
    status_label = serializers.CharField(source="get_status_display", read_only=True)
    plan_slug = serializers.CharField(source="plan.slug", read_only=True)
    benefit_percent = serializers.IntegerField(read_only=True)
    hold_expires_at = serializers.DateTimeField(read_only=True)
    refund_status_label = serializers.CharField(source="get_refund_status_display", read_only=True)
    user_email = serializers.CharField(source="user.email", read_only=True)
    places = serializers.SerializerMethodField()

    class Meta:
        model = Membership
        fields = (
            "card_number", "status", "status_label", "plan_name", "plan_slug", "discount_percent", "free_entry",
            "benefit_percent", "max_visitors_per_booking", "duration_days", "holder_name", "starts_on", "ends_on",
            "total_amount", "payment_method", "payment_id", "gateway", "paid_at", "created_at", "cancelled_at",
            "hold_expires_at", "refund_amount", "refund_status", "refund_status_label", "user_email", "places",
        )

    def get_places(self, obj):
        return [m.name for m in obj.plan.places.all()]


class MembershipCreateSerializer(serializers.Serializer):
    plan = serializers.SlugRelatedField(slug_field="slug", queryset=MembershipPlan.objects.all())
    holder_name = serializers.CharField(max_length=120, required=False, allow_blank=True, default="")
