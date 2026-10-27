from decimal import Decimal

from django.db.models import Sum
from rest_framework import serializers

from museums.models import Museum

from . import services
from .models import GiftVoucher, PromoCode, VoucherRedemption


class PromoCodeSerializer(serializers.ModelSerializer):
    museums = serializers.PrimaryKeyRelatedField(many=True, queryset=Museum.objects.all(), required=False)
    museum_names = serializers.SerializerMethodField()
    uses_count = serializers.SerializerMethodField()
    total_discount = serializers.SerializerMethodField()
    created_by_email = serializers.CharField(source="created_by.email", read_only=True, default=None)

    class Meta:
        model = PromoCode
        fields = (
            "id", "code", "description", "discount_type", "value", "max_discount", "min_order_amount",
            "valid_from", "valid_to", "usage_limit", "per_user_limit", "scope", "museums", "museum_names",
            "place_types", "applies_to", "first_booking_only", "is_active", "created_by_email", "created_at",
            "uses_count", "total_discount",
        )
        read_only_fields = ("created_at",)

    def get_museum_names(self, obj):
        return [m.name for m in obj.museums.all()]

    def get_uses_count(self, obj):
        return services.active_redemptions(obj).count()

    def get_total_discount(self, obj):
        total = services.active_redemptions(obj).filter(booking__status__in=services.PAID_STATUSES).aggregate(
            s=Sum("amount")
        )["s"]
        return str(total or Decimal("0.00"))

    def validate_code(self, value):
        code = services.normalize(value)
        if not code:
            raise serializers.ValidationError("Enter a code.")
        if code.startswith("GV-"):
            raise serializers.ValidationError("Codes starting with GV- are reserved for gift vouchers.")
        qs = PromoCode.objects.filter(code__iexact=code)
        if self.instance:
            qs = qs.exclude(pk=self.instance.pk)
        if qs.exists():
            raise serializers.ValidationError("A promo code with this code already exists.")
        return code

    def validate_place_types(self, value):
        valid = set(Museum.PlaceType.values)
        types = [t.strip().lower() for t in (value or "").split(",") if t.strip()]
        bad = [t for t in types if t not in valid]
        if bad:
            raise serializers.ValidationError(f"Unknown place type(s): {', '.join(bad)}.")
        return ",".join(types)

    def validate(self, attrs):
        get = lambda k: attrs.get(k, getattr(self.instance, k, None) if self.instance else PromoCode._meta.get_field(k).get_default())  # noqa: E731
        value = get("value")
        if value is None or value <= 0:
            raise serializers.ValidationError({"value": "Enter a value above 0."})
        if get("discount_type") == PromoCode.DiscountType.PERCENT and value > 100:
            raise serializers.ValidationError({"value": "A percentage can't be more than 100."})
        if get("valid_from") and get("valid_to") and get("valid_to") <= get("valid_from"):
            raise serializers.ValidationError({"valid_to": "Must be after the start."})
        scope = get("scope")
        if scope == PromoCode.Scope.MUSEUMS:
            museums = attrs["museums"] if "museums" in attrs else (list(self.instance.museums.all()) if self.instance else [])
            if not museums:
                raise serializers.ValidationError({"museums": "Pick at least one place."})
        if scope == PromoCode.Scope.PLACE_TYPES and not get("place_types"):
            raise serializers.ValidationError({"place_types": "Pick at least one place type."})
        return attrs


class VoucherRedemptionSerializer(serializers.ModelSerializer):
    booking_reference = serializers.CharField(source="booking.reference", read_only=True)
    booking_status = serializers.CharField(source="booking.status", read_only=True)

    class Meta:
        model = VoucherRedemption
        fields = ("id", "booking_reference", "booking_status", "amount", "created_at", "reversed_at")


class GiftVoucherSerializer(serializers.ModelSerializer):
    issued_by_email = serializers.CharField(source="issued_by.email", read_only=True, default=None)
    is_expired = serializers.BooleanField(read_only=True)
    used_amount = serializers.SerializerMethodField()
    send_email = serializers.BooleanField(write_only=True, required=False, default=False)
    redemptions = VoucherRedemptionSerializer(many=True, read_only=True)

    class Meta:
        model = GiftVoucher
        fields = (
            "id", "code", "initial_value", "balance", "used_amount", "purchaser_name", "purchaser_email",
            "recipient_name", "recipient_email", "message", "valid_until", "is_active", "is_expired",
            "issued_by_email", "created_at", "send_email", "redemptions",
        )
        read_only_fields = ("code", "balance", "created_at")

    def get_used_amount(self, obj):
        return str(obj.initial_value - obj.balance)

    def validate_initial_value(self, value):
        if value <= 0:
            raise serializers.ValidationError("Enter a value above 0.")
        if self.instance and value != self.instance.initial_value:
            raise serializers.ValidationError("The value of an issued voucher can't be changed.")
        return value

    def validate(self, attrs):
        if attrs.get("send_email") and not attrs.get("recipient_email", getattr(self.instance, "recipient_email", "")):
            raise serializers.ValidationError({"recipient_email": "Enter the recipient's email to send the voucher."})
        return attrs

    def create(self, validated_data):
        validated_data.pop("send_email", None)
        validated_data["balance"] = validated_data["initial_value"]
        return super().create(validated_data)

    def update(self, instance, validated_data):
        validated_data.pop("send_email", None)
        return super().update(instance, validated_data)


class ApplyCodeSerializer(serializers.Serializer):
    code = serializers.CharField(max_length=40)


class RemoveCodeSerializer(serializers.Serializer):
    kind = serializers.ChoiceField(choices=["promo", "voucher"], required=False, allow_blank=True)
