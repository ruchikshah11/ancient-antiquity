import re

from django.contrib.auth import get_user_model
from django.contrib.auth.password_validation import validate_password
from rest_framework import serializers

from bookings.models import Booking
from bookings.serializers import BookingSerializer, CounterSaleSerializer
from museums.models import Museum

from .models import AgentPayment, AgentProfile, KioskDevice, PartnerAccount, Settlement
from .services import agent_can_cancel

User = get_user_model()
GSTIN_RE = re.compile(r"^[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z][1-9A-Z]Z[0-9A-Z]$")
PHONE_RE = r"^\+?[0-9]{10,13}$"


# --------------------------------------------------------------------------------------- tour operators

class AgentApplySerializer(serializers.ModelSerializer):
    contact_phone = serializers.RegexField(PHONE_RE, error_messages={"invalid": "Enter a valid phone number."})

    class Meta:
        model = AgentProfile
        fields = ("company_name", "gstin", "contact_phone", "city", "message")

    def validate_gstin(self, value):
        value = (value or "").strip().upper()
        if value and not GSTIN_RE.match(value):
            raise serializers.ValidationError("Enter a valid 15-character GSTIN, or leave it empty.")
        return value


class AgentProfileSerializer(serializers.ModelSerializer):
    email = serializers.CharField(source="user.email", read_only=True)
    name = serializers.SerializerMethodField()
    role = serializers.CharField(source="user.role", read_only=True)
    status_label = serializers.CharField(source="get_status_display", read_only=True)
    credit_available = serializers.DecimalField(max_digits=12, decimal_places=2, read_only=True)
    approved_by_email = serializers.CharField(source="approved_by.email", read_only=True, default=None)

    class Meta:
        model = AgentProfile
        fields = (
            "id", "email", "name", "role", "company_name", "gstin", "contact_phone", "city", "message",
            "commission_percent", "credit_limit", "balance", "credit_available", "status", "status_label",
            "is_approved", "approved_by_email", "approved_at", "admin_note", "created_at",
        )
        read_only_fields = fields

    def get_name(self, obj):
        return obj.user.get_full_name() or obj.user.email


class AgentAdminUpdateSerializer(serializers.ModelSerializer):
    class Meta:
        model = AgentProfile
        fields = ("commission_percent", "credit_limit", "company_name", "gstin", "contact_phone", "city", "admin_note")

    def validate_credit_limit(self, value):
        if value < 0:
            raise serializers.ValidationError("Credit limit cannot be negative.")
        return value

    validate_gstin = AgentApplySerializer.validate_gstin


class AgentPaymentSerializer(serializers.ModelSerializer):
    recorded_by_email = serializers.CharField(source="recorded_by.email", read_only=True, default=None)
    received_on = serializers.DateField(required=False)

    class Meta:
        model = AgentPayment
        fields = ("id", "amount", "reference", "note", "received_on", "recorded_by_email", "created_at")
        read_only_fields = ("id", "recorded_by_email", "created_at")


class AgentBookingSerializer(BookingSerializer):
    """A booking as the tour operator sees it: plus commission and whether they can still cancel it."""

    commission_amount = serializers.DecimalField(max_digits=10, decimal_places=2, read_only=True)
    agent_can_cancel = serializers.SerializerMethodField()

    class Meta(BookingSerializer.Meta):
        fields = BookingSerializer.Meta.fields + ("commission_amount", "agent_can_cancel")

    def get_agent_can_cancel(self, obj):
        return agent_can_cancel(obj)


class StatementBookingSerializer(serializers.ModelSerializer):
    museum_name = serializers.CharField(source="museum.name", read_only=True)
    slot_start = serializers.TimeField(source="slot.start_time", read_only=True)
    status_label = serializers.CharField(source="get_status_display", read_only=True)

    class Meta:
        model = Booking
        fields = (
            "reference", "created_at", "museum_name", "visit_date", "slot_start", "visitor_name", "organisation_name",
            "is_group", "total_visitors", "total_amount", "commission_amount", "status", "status_label",
        )


# --------------------------------------------------------------------------------------- settlements

class PartnerAccountSerializer(serializers.ModelSerializer):
    museum = serializers.SlugRelatedField(slug_field="slug", queryset=Museum.objects.all())
    museum_name = serializers.CharField(source="museum.name", read_only=True)
    account_number = serializers.CharField(write_only=True, required=False, allow_blank=True, max_length=30)
    masked_account_number = serializers.CharField(read_only=True)

    class Meta:
        model = PartnerAccount
        fields = (
            "id", "museum", "museum_name", "account_holder", "bank_name", "account_number", "masked_account_number",
            "ifsc", "razorpay_account_id", "platform_fee_percent", "updated_at",
        )

    def validate_account_number(self, value):
        value = value.replace(" ", "")
        if value and not value.isdigit():
            raise serializers.ValidationError("Account number must contain digits only.")
        return value

    def validate_ifsc(self, value):
        value = (value or "").strip().upper()
        if value and not re.match(r"^[A-Z]{4}0[A-Z0-9]{6}$", value):
            raise serializers.ValidationError("Enter a valid IFSC code (e.g. SBIN0001234).")
        return value

    def validate_razorpay_account_id(self, value):
        value = (value or "").strip()
        if value and not value.startswith("acc_"):
            raise serializers.ValidationError("Razorpay linked account ids start with acc_.")
        return value


class SettlementSerializer(serializers.ModelSerializer):
    museum_name = serializers.CharField(source="museum.name", read_only=True)
    museum_slug = serializers.CharField(source="museum.slug", read_only=True)
    city_name = serializers.CharField(source="museum.city.name", read_only=True)
    status_label = serializers.CharField(source="get_status_display", read_only=True)
    gross_total = serializers.DecimalField(max_digits=12, decimal_places=2, read_only=True)
    approved_by_email = serializers.CharField(source="approved_by.email", read_only=True, default=None)
    created_by_email = serializers.CharField(source="created_by.email", read_only=True, default=None)

    class Meta:
        model = Settlement
        fields = (
            "id", "museum_name", "museum_slug", "city_name", "period_start", "period_end", "booking_count",
            "visitor_count", "gross_online", "gross_kiosk", "gross_counter", "gross_agent", "gross_total", "refunds",
            "platform_fee_percent", "platform_fee", "gst_on_fee", "net_payable", "status", "status_label",
            "approved_by_email", "approved_at", "paid_reference", "paid_at", "created_by_email", "created_at",
        )
        read_only_fields = fields


class SettlementGenerateSerializer(serializers.Serializer):
    # "from" is a keyword, so the field is mapped in validate().
    to = serializers.DateField()
    museum = serializers.SlugRelatedField(slug_field="slug", queryset=Museum.objects.all(), required=False)

    def to_internal_value(self, data):
        value = super().to_internal_value(data)
        start = serializers.DateField().run_validation(data.get("from"))
        if start is None:
            raise serializers.ValidationError({"from": "This field is required."})
        value["start"] = start
        return value


# --------------------------------------------------------------------------------------- kiosks

class KioskSerializer(serializers.ModelSerializer):
    email = serializers.EmailField(source="user.email", read_only=True)
    museums = serializers.SlugRelatedField(slug_field="slug", many=True, queryset=Museum.objects.all())
    museum_names = serializers.SerializerMethodField()
    last_login = serializers.DateTimeField(source="user.last_login", read_only=True)

    class Meta:
        model = KioskDevice
        fields = ("id", "name", "email", "museums", "museum_names", "is_active", "last_login", "created_at")
        read_only_fields = ("id", "email", "museum_names", "last_login", "created_at")

    def get_museum_names(self, obj):
        return [m.name for m in obj.museums.all()]


class KioskCreateSerializer(KioskSerializer):
    email = serializers.EmailField(write_only=True)
    password = serializers.CharField(write_only=True, min_length=8, style={"input_type": "password"})

    class Meta(KioskSerializer.Meta):
        fields = KioskSerializer.Meta.fields + ("password",)
        read_only_fields = ("id", "museum_names", "last_login", "created_at")

    def validate_email(self, value):
        value = value.strip().lower()
        if User.objects.filter(email__iexact=value).exists():
            raise serializers.ValidationError("A user with this email already exists.")
        return value

    def validate_password(self, value):
        validate_password(value)
        return value

    def create(self, validated_data):
        email = validated_data.pop("email")
        password = validated_data.pop("password")
        museums = validated_data.pop("museums", [])
        user = User.objects.create_user(email=email, password=password, role=User.Role.KIOSK,
                                        first_name="Kiosk", last_name=validated_data["name"][:150])
        device = KioskDevice.objects.create(user=user, **validated_data)
        device.museums.set(museums)
        return device

    def to_representation(self, instance):
        return KioskSerializer(instance, context=self.context).data


class KioskUpdateSerializer(KioskSerializer):
    password = serializers.CharField(write_only=True, min_length=8, required=False)

    class Meta(KioskSerializer.Meta):
        fields = KioskSerializer.Meta.fields + ("password",)

    def validate_password(self, value):
        validate_password(value)
        return value

    def update(self, instance, validated_data):
        password = validated_data.pop("password", None)
        device = super().update(instance, validated_data)
        user = device.user
        if password:
            user.set_password(password)
        user.is_active = device.is_active  # a disabled kiosk can no longer sign in
        user.save()
        return device

    def to_representation(self, instance):
        return KioskSerializer(instance, context=self.context).data


class KioskBookingSerializer(CounterSaleSerializer):
    """Walk-in self-service sale: today only, a running slot is fine; paid afterwards through the normal checkout."""

    payment_method = None
    check_in = None
    visitor_name = serializers.CharField(max_length=120, required=False, default="Kiosk visitor")
