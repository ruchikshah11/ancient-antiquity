from django.conf import settings
from rest_framework import serializers

from museums.models import Museum

from .models import MAX_AMOUNT, MIN_AMOUNT, PAN_RE, Donation
from .words import rupees_in_words


def trust_info():
    return {
        "name": settings.DONATION_TRUST_NAME or "Ancient Antiquity Heritage Foundation",
        "pan": settings.DONATION_TRUST_PAN,
        "registration_80g": settings.DONATION_80G_NUMBER,
    }


class DonationCreateSerializer(serializers.ModelSerializer):
    museum = serializers.SlugRelatedField(
        slug_field="slug", queryset=Museum.objects.filter(is_active=True), required=False, allow_null=True
    )
    amount = serializers.DecimalField(max_digits=11, decimal_places=2, min_value=MIN_AMOUNT, max_value=MAX_AMOUNT)
    donor_pan = serializers.CharField(max_length=12, required=False, allow_blank=True)
    donor_address = serializers.CharField(max_length=300, required=False, allow_blank=True)
    donor_phone = serializers.CharField(max_length=15, required=False, allow_blank=True)

    class Meta:
        model = Donation
        fields = ("museum", "amount", "donor_name", "donor_email", "donor_phone", "donor_pan", "donor_address",
                  "wants_80g")

    def validate_donor_pan(self, value):
        value = (value or "").strip().upper().replace(" ", "")
        if value and not PAN_RE.match(value):
            raise serializers.ValidationError("Enter a valid PAN, e.g. ABCDE1234F.")
        return value

    def validate_donor_name(self, value):
        value = value.strip()
        if not value:
            raise serializers.ValidationError("Enter the donor's name.")
        return value

    def validate(self, attrs):
        attrs["donor_address"] = (attrs.get("donor_address") or "").strip()
        if attrs.get("wants_80g"):
            errors = {}
            if not attrs.get("donor_pan"):
                errors["donor_pan"] = "A PAN is needed to claim the 80G deduction."
            if not attrs["donor_address"]:
                errors["donor_address"] = "An address is needed on an 80G receipt."
            if errors:
                raise serializers.ValidationError(errors)
        return attrs


class DonationSerializer(serializers.ModelSerializer):
    status_label = serializers.CharField(source="get_status_display", read_only=True)
    museum_slug = serializers.CharField(source="museum.slug", read_only=True, default=None)
    museum_name = serializers.CharField(source="museum.name", read_only=True, default=None)
    purpose = serializers.CharField(read_only=True)
    amount_in_words = serializers.SerializerMethodField()
    is_80g_eligible = serializers.BooleanField(read_only=True)
    trust = serializers.SerializerMethodField()

    class Meta:
        model = Donation
        fields = (
            "reference", "status", "status_label", "amount", "amount_in_words", "museum_slug", "museum_name",
            "purpose", "donor_name", "donor_email", "donor_phone", "donor_pan", "donor_address", "wants_80g",
            "is_80g_eligible", "receipt_number", "payment_method", "payment_id", "gateway", "created_at",
            "paid_at", "refunded_at", "trust",
        )
        read_only_fields = fields

    def get_amount_in_words(self, obj):
        return rupees_in_words(obj.amount)

    def get_trust(self, obj):
        return trust_info()


class AdminDonationSerializer(DonationSerializer):
    user_email = serializers.CharField(source="user.email", read_only=True, default=None)

    class Meta(DonationSerializer.Meta):
        fields = tuple(f for f in DonationSerializer.Meta.fields if f != "trust") + (
            "user_email", "gateway_order_id", "refund_id",
        )
        read_only_fields = fields
