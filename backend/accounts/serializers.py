from django.contrib.auth import get_user_model
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError as DjangoValidationError
from rest_framework import serializers
from rest_framework_simplejwt.serializers import TokenObtainSerializer

User = get_user_model()


class UserSerializer(serializers.ModelSerializer):
    is_panel_user = serializers.BooleanField(read_only=True)
    is_admin_role = serializers.BooleanField(read_only=True)
    totp_enabled = serializers.BooleanField(read_only=True)
    two_factor_setup_required = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = (
            "id", "email", "first_name", "last_name", "phone", "role",
            "is_active", "is_panel_user", "is_admin_role", "date_joined", "last_login",
            "totp_enabled", "two_factor_setup_required",
        )
        read_only_fields = ("id", "email", "role", "is_active", "date_joined", "last_login")

    def get_two_factor_setup_required(self, obj):
        from .auth_services import two_factor_setup_required

        return two_factor_setup_required(obj)


class AdminUserSerializer(UserSerializer):
    """Admins may change role and active flag."""

    booking_count = serializers.IntegerField(read_only=True)

    class Meta(UserSerializer.Meta):
        fields = UserSerializer.Meta.fields + ("booking_count", "is_sample")
        read_only_fields = ("id", "email", "date_joined", "last_login", "totp_enabled", "is_sample")


class RegisterSerializer(serializers.ModelSerializer):
    password = serializers.CharField(write_only=True)

    class Meta:
        model = User
        fields = ("email", "password", "first_name", "last_name", "phone")

    def validate_email(self, value):
        # Emails are case-insensitive: Asha@example.com and asha@example.com are the same person.
        value = value.strip().lower()
        if User.objects.filter(email__iexact=value).exists():
            raise serializers.ValidationError("user with this email already exists.")
        return value

    def validate_password(self, value):
        validate_password(value)
        return value

    def create(self, validated_data):
        return User.objects.create_user(**validated_data)


class LoginSerializer(TokenObtainSerializer):
    """Checks email + password only; LoginView decides between tokens and a two-step challenge."""

    def validate(self, attrs):
        attrs[self.username_field] = (attrs.get(self.username_field) or "").strip().lower()
        super().validate(attrs)  # raises AuthenticationFailed for a wrong email/password or inactive user
        return {"user": self.user}


class GoogleLoginSerializer(serializers.Serializer):
    credential = serializers.CharField(max_length=5000)


class OTPDestinationSerializer(serializers.Serializer):
    """Exactly one of email / phone."""

    email = serializers.EmailField(required=False, allow_blank=True)
    phone = serializers.CharField(required=False, allow_blank=True, max_length=20)

    def validate(self, attrs):
        from .auth_services import normalise_phone

        email = (attrs.get("email") or "").strip().lower()
        phone = normalise_phone(attrs.get("phone") or "")
        if bool(email) == bool(attrs.get("phone")):
            raise serializers.ValidationError("Enter either an email address or a mobile number.")
        if attrs.get("phone") and not (10 <= len(phone) <= 15):
            raise serializers.ValidationError({"phone": ["Enter a valid mobile number."]})
        attrs["channel"] = "email" if email else "sms"
        attrs["destination"] = email or phone
        return attrs


class OTPVerifySerializer(OTPDestinationSerializer):
    code = serializers.CharField(max_length=10)


class TwoFactorVerifySerializer(serializers.Serializer):
    ticket = serializers.CharField(max_length=1000)
    code = serializers.CharField(max_length=20)


class TwoFactorCodeSerializer(serializers.Serializer):
    code = serializers.CharField(max_length=20)


class ChangePasswordSerializer(serializers.Serializer):
    old_password = serializers.CharField()
    new_password = serializers.CharField()

    def validate_new_password(self, value):
        validate_password(value, self.context["request"].user)
        return value


class PasswordResetRequestSerializer(serializers.Serializer):
    email = serializers.EmailField()


class PasswordResetConfirmSerializer(serializers.Serializer):
    """Checks the emailed uid/token pair and the new password; exposes the user as validated_data["user"]."""

    uid = serializers.CharField()
    token = serializers.CharField()
    new_password = serializers.CharField()

    INVALID_LINK = "This reset link is invalid or has expired. Please request a new one."

    def validate(self, attrs):
        from django.contrib.auth.tokens import default_token_generator
        from django.utils.encoding import force_str
        from django.utils.http import urlsafe_base64_decode

        try:
            user = User.objects.get(pk=force_str(urlsafe_base64_decode(attrs["uid"])), is_active=True)
        except (TypeError, ValueError, OverflowError, User.DoesNotExist):
            raise serializers.ValidationError({"token": [self.INVALID_LINK]})
        if not default_token_generator.check_token(user, attrs["token"]):
            raise serializers.ValidationError({"token": [self.INVALID_LINK]})
        try:
            validate_password(attrs["new_password"], user)
        except DjangoValidationError as exc:
            raise serializers.ValidationError({"new_password": list(exc.messages)})
        attrs["user"] = user
        return attrs


class PartnerCreateSerializer(serializers.Serializer):
    """Admin -> Users -> Add partner: a sign-in for a place's management (role partner, read-only portal)."""

    email = serializers.EmailField()
    password = serializers.CharField(write_only=True)
    first_name = serializers.CharField(max_length=150, required=False, allow_blank=True)
    last_name = serializers.CharField(max_length=150, required=False, allow_blank=True)
    phone = serializers.CharField(max_length=15, required=False, allow_blank=True)
    museums = serializers.ListField(child=serializers.CharField(max_length=170), allow_empty=False)

    def validate_email(self, value):
        value = value.strip().lower()
        if User.objects.filter(email__iexact=value).exists():
            raise serializers.ValidationError("user with this email already exists.")
        return value

    def validate_password(self, value):
        validate_password(value)
        return value

    def validate_museums(self, value):
        from museums.models import Museum

        slugs = list(dict.fromkeys(s.strip() for s in value if s.strip()))
        museums = list(Museum.objects.filter(slug__in=slugs))
        missing = sorted(set(slugs) - {m.slug for m in museums})
        if missing:
            raise serializers.ValidationError(f"Unknown place(s): {', '.join(missing)}")
        if not museums:
            raise serializers.ValidationError("Choose at least one place.")
        return museums

    def create(self, validated_data):
        museums = validated_data.pop("museums")
        user = User.objects.create_user(role=User.Role.PARTNER, **validated_data)
        user.partner_places.set(museums)
        return user
