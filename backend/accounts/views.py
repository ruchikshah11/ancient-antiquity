from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.tokens import default_token_generator
from django.core.exceptions import ValidationError as DjangoValidationError
from django.core.validators import EmailValidator
from django.db.models import Count, IntegerField, OuterRef, Subquery
from django.db.models.functions import Coalesce
from django.utils.encoding import force_bytes
from django.utils.http import urlsafe_base64_encode
from rest_framework import generics, mixins, permissions, status, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response
import pyotp
from rest_framework.exceptions import AuthenticationFailed
from rest_framework.throttling import AnonRateThrottle, SimpleRateThrottle
from rest_framework.views import APIView
from rest_framework_simplejwt.tokens import RefreshToken

from audit.services import record
from bookings.models import Booking

from notifications.services import send_password_reset

from . import auth_services as auth
from . import exports
from .permissions import IsAdminRole, IsPanelUser
from .serializers import (
    AdminUserSerializer,
    PartnerCreateSerializer,
    ChangePasswordSerializer,
    GoogleLoginSerializer,
    LoginSerializer,
    OTPDestinationSerializer,
    OTPVerifySerializer,
    TwoFactorCodeSerializer,
    TwoFactorVerifySerializer,
    PasswordResetConfirmSerializer,
    PasswordResetRequestSerializer,
    RegisterSerializer,
    UserSerializer,
)

User = get_user_model()


class RegisterView(generics.CreateAPIView):
    serializer_class = RegisterSerializer
    permission_classes = [permissions.AllowAny]

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = serializer.save()
        refresh = RefreshToken.for_user(user)
        return Response(
            {
                "access": str(refresh.access_token),
                "refresh": str(refresh),
                "user": UserSerializer(user).data,
            },
            status=status.HTTP_201_CREATED,
        )


class IPWindowThrottle(SimpleRateThrottle):
    """Per-IP limit of `limit` requests per `window` seconds (DRF rate strings can't say "per 10 minutes")."""

    limit = 5
    window = 600

    def get_rate(self):
        return f"{self.limit}/{self.window}s"

    def parse_rate(self, rate):
        return self.limit, self.window

    def get_cache_key(self, request, view):
        return self.cache_format % {"scope": self.scope, "ident": self.get_ident(request)}


class OTPRequestThrottle(IPWindowThrottle):
    scope = "otp_request"
    limit, window = 5, 600


class OTPVerifyThrottle(IPWindowThrottle):
    scope = "otp_verify"
    limit, window = 20, 600


class TwoFactorVerifyThrottle(IPWindowThrottle):
    scope = "2fa_verify"
    limit, window = 10, 300


class LoginView(APIView):
    """Email + password. Answers {access, refresh, user} or {two_factor_required, ticket}."""

    permission_classes = [permissions.AllowAny]
    authentication_classes = []

    def get_authenticate_header(self, request):
        return 'Bearer realm="api"'  # wrong credentials answer 401, as before

    def post(self, request):
        serializer = LoginSerializer(data=request.data)
        try:
            serializer.is_valid(raise_exception=True)
        except AuthenticationFailed:
            email = str(request.data.get("email") or "").strip().lower()[:254]
            auth.login_failed(request, email, "password", "wrong email or password")
            raise
        return Response(auth.complete_login(request, serializer.validated_data["user"], "password"))


class LoginMethodsView(APIView):
    """Which sign-in methods the login screen should offer."""

    permission_classes = [permissions.AllowAny]
    authentication_classes = []

    def get(self, request):
        return Response(auth.methods())


class GoogleLoginView(APIView):
    permission_classes = [permissions.AllowAny]
    authentication_classes = []

    def post(self, request):
        if not settings.GOOGLE_CLIENT_ID:
            return Response({"detail": "Google sign-in is not available."}, status=400)
        serializer = GoogleLoginSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            claims = auth.verify_google_credential(serializer.validated_data["credential"])
        except Exception as exc:  # ValueError for bad tokens; transport errors fetching Google's keys
            auth.login_failed(request, "", "google", f"invalid token: {str(exc)[:200]}")
            return Response({"detail": "Google sign-in failed. Please try again."}, status=400)
        email = (claims.get("email") or "").strip().lower()
        if not email or not claims.get("email_verified"):
            auth.login_failed(request, email, "google", "email not verified")
            return Response({"detail": "Your Google account email is not verified."}, status=400)
        user, created = auth.user_for_google(claims)
        if not user.is_active:
            auth.login_failed(request, email, "google", "account disabled")
            return Response({"detail": "This account has been disabled."}, status=403)
        data = auth.complete_login(request, user, "google")
        if created:
            data["created"] = True
        return Response(data)


class OTPRequestView(APIView):
    """Send a 6-digit sign-in code by email or SMS. Always answers the same way."""

    permission_classes = [permissions.AllowAny]
    authentication_classes = []
    throttle_classes = [OTPRequestThrottle]

    def post(self, request):
        if not settings.OTP_LOGIN_ENABLED:
            return Response({"detail": "Sign-in codes are not available."}, status=400)
        serializer = OTPDestinationSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        channel, destination = serializer.validated_data["channel"], serializer.validated_data["destination"]
        if channel == "sms" and not auth.sms_available():
            return Response({"detail": "Sign-in by mobile is not available right now. Please use email."}, status=400)
        code = auth.issue_otp(destination, channel)
        where = "email address" if channel == "email" else "mobile number"
        data = {
            "detail": f"If this {where} can be used, a 6-digit code is on its way.",
            "expires_in_minutes": settings.OTP_TTL_MINUTES,
        }
        if code and auth.dev_code_visible(channel):
            # DEBUG + no real SMS/email service: hand the code to the screen so sign-in can be tested.
            data["dev_code"] = code
        return Response(data)


class OTPVerifyView(APIView):
    permission_classes = [permissions.AllowAny]
    authentication_classes = []
    throttle_classes = [OTPVerifyThrottle]

    def post(self, request):
        if not settings.OTP_LOGIN_ENABLED:
            return Response({"detail": "Sign-in codes are not available."}, status=400)
        serializer = OTPVerifySerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        channel, destination = serializer.validated_data["channel"], serializer.validated_data["destination"]
        method = f"otp_{channel}"
        ok, message = auth.check_otp(destination, channel, serializer.validated_data["code"])
        if not ok:
            auth.login_failed(request, destination, method, message)
            return Response({"code": [message]}, status=400)
        created = False
        if channel == "email":
            user = User.objects.filter(email__iexact=destination).first()
            if user is None:
                user, created = User.objects.create_user(email=destination, password=None), True
        else:
            user = auth.user_for_phone(destination)
            if user is None:
                # Verified number without an account: let them finish sign-up (name + email) in one more step.
                return Response({
                    "register_required": True,
                    "phone_ticket": auth.make_phone_signup_ticket(destination),
                    "detail": "Your number is verified. Add your name and email to create your account.",
                })
        if not user.is_active:
            auth.login_failed(request, destination, method, "account disabled")
            return Response({"detail": "This account has been disabled."}, status=403)
        data = auth.complete_login(request, user, method)
        if created:
            data["created"] = True
        return Response(data)


class OTPPhoneRegisterView(APIView):
    """Finish sign-up for a mobile number that was just verified by code: name + email, then signed in."""

    permission_classes = [permissions.AllowAny]
    authentication_classes = []
    throttle_classes = [OTPVerifyThrottle]

    def post(self, request):
        number = auth.read_phone_signup_ticket(request.data.get("phone_ticket") or "")
        if not number:
            return Response({"detail": "Verification expired. Please request a new code.", "expired": True}, status=400)
        if auth.user_for_phone(number):
            return Response({"detail": "This mobile number already has an account. Please sign in."}, status=400)
        email = (request.data.get("email") or "").strip().lower()
        first_name = (request.data.get("first_name") or "").strip()[:150]
        last_name = (request.data.get("last_name") or "").strip()[:150]
        errors = {}
        if not first_name:
            errors["first_name"] = ["Please enter your name."]
        try:
            EmailValidator()(email)
        except DjangoValidationError:
            errors["email"] = ["Enter a valid email address (your e-tickets are sent there)."]
        if not errors.get("email") and User.objects.filter(email__iexact=email).exists():
            errors["email"] = ["This email already has an account. Sign in with it and add your mobile number in My profile."]
        if errors:
            return Response(errors, status=400)
        user = User.objects.create_user(email=email, password=None, first_name=first_name, last_name=last_name,
                                        phone=f"+{number}")
        data = auth.complete_login(request, user, "otp_sms")
        data["created"] = True
        return Response(data, status=201)


class TwoFactorVerifyView(APIView):
    """Second step of sign-in: {ticket, code} (authenticator or backup code) -> tokens."""

    permission_classes = [permissions.AllowAny]
    authentication_classes = []
    throttle_classes = [TwoFactorVerifyThrottle]

    def post(self, request):
        serializer = TwoFactorVerifySerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user, method = auth.read_ticket(serializer.validated_data["ticket"])
        if user is None or not user.totp_enabled:
            return Response({"detail": "Your sign-in has expired. Please sign in again.", "expired": True}, status=400)
        if not auth.verify_second_factor(user, serializer.validated_data["code"]):
            auth.login_failed(request, user.email, f"{method}+2fa", "wrong verification code")
            return Response({"code": ["That code is not correct."]}, status=400)
        record(request, "login", user=user, object_repr=user.email, status_code=200, changes={"method": f"{method}+2fa"})
        return Response(auth.token_payload(user))


class TwoFactorStatusView(APIView):
    permission_classes = [IsPanelUser]

    def get(self, request):
        user = request.user
        return Response({
            "enabled": user.totp_enabled,
            "backup_codes_left": len(user.totp_backup_codes or []) if user.totp_enabled else 0,
            "required": settings.STAFF_2FA_REQUIRED,
        })


class TwoFactorSetupView(APIView):
    """Start set-up: a new secret (not active until confirmed with a code)."""

    permission_classes = [IsPanelUser]

    def post(self, request):
        user = request.user
        if user.totp_enabled:
            return Response({"detail": "Two-step verification is already on."}, status=400)
        user.totp_secret = pyotp.random_base32()
        user.save(update_fields=["totp_secret"])
        return Response({"secret": user.totp_secret, "otpauth_uri": auth.totp_uri(user)})


class TwoFactorEnableView(APIView):
    permission_classes = [IsPanelUser]

    def post(self, request):
        serializer = TwoFactorCodeSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = request.user
        if user.totp_enabled:
            return Response({"detail": "Two-step verification is already on."}, status=400)
        if not user.totp_secret:
            return Response({"detail": "Start the set-up first."}, status=400)
        if not auth.verify_second_factor(user, serializer.validated_data["code"], allow_backup=False):
            return Response({"code": ["That code is not correct. Check the time on your phone and try again."]}, status=400)
        codes = auth.new_backup_codes(user)
        user.totp_enabled = True
        user.save(update_fields=["totp_enabled", "totp_backup_codes"])
        return Response({"enabled": True, "backup_codes": codes, "user": UserSerializer(user).data})


class TwoFactorDisableView(APIView):
    permission_classes = [IsPanelUser]

    def post(self, request):
        serializer = TwoFactorCodeSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = request.user
        if not user.totp_enabled:
            return Response({"detail": "Two-step verification is not on."}, status=400)
        if not auth.verify_second_factor(user, serializer.validated_data["code"]):
            return Response({"code": ["That code is not correct."]}, status=400)
        user.totp_enabled, user.totp_secret, user.totp_backup_codes = False, "", []
        user.save(update_fields=["totp_enabled", "totp_secret", "totp_backup_codes"])
        return Response({"enabled": False, "user": UserSerializer(user).data})


class TwoFactorBackupCodesView(APIView):
    """New set of backup codes (old ones stop working); needs an authenticator code."""

    permission_classes = [IsPanelUser]

    def post(self, request):
        serializer = TwoFactorCodeSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = request.user
        if not user.totp_enabled:
            return Response({"detail": "Two-step verification is not on."}, status=400)
        if not auth.verify_second_factor(user, serializer.validated_data["code"], allow_backup=False):
            return Response({"code": ["That code is not correct."]}, status=400)
        codes = auth.new_backup_codes(user)
        user.save(update_fields=["totp_backup_codes"])
        return Response({"backup_codes": codes})


class MeView(generics.RetrieveUpdateAPIView):
    serializer_class = UserSerializer

    def get_object(self):
        return self.request.user


class ChangePasswordView(APIView):
    def post(self, request):
        serializer = ChangePasswordSerializer(data=request.data, context={"request": request})
        serializer.is_valid(raise_exception=True)
        if not request.user.check_password(serializer.validated_data["old_password"]):
            return Response({"old_password": ["Incorrect password."]}, status=400)
        request.user.set_password(serializer.validated_data["new_password"])
        request.user.save()
        return Response({"detail": "Password updated."})


class PasswordResetThrottle(AnonRateThrottle):
    """Per-IP limit on reset requests/confirms; rate lives here so settings.py needs no throttle config."""

    scope = "password_reset"
    rate = "5/hour"


class PasswordResetRequestView(APIView):
    """Email a reset link. Always answers the same way so it can't be used to discover accounts."""

    permission_classes = [permissions.AllowAny]
    authentication_classes = []  # a stale/expired JWT on the login page must not cause a 401
    throttle_classes = [PasswordResetThrottle]

    GENERIC_MESSAGE = "If an account exists for that email, we've sent a reset link."

    def post(self, request):
        serializer = PasswordResetRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = User.objects.filter(email__iexact=serializer.validated_data["email"], is_active=True).first()
        if user:
            uid = urlsafe_base64_encode(force_bytes(user.pk))
            token = default_token_generator.make_token(user)
            send_password_reset(user, f"{settings.FRONTEND_URL}/reset-password/{uid}/{token}")
        return Response({"detail": self.GENERIC_MESSAGE})


class PasswordResetConfirmView(APIView):
    """Set a new password from an emailed uid/token link (the token dies once the password changes)."""

    permission_classes = [permissions.AllowAny]
    authentication_classes = []
    throttle_classes = [PasswordResetThrottle]

    def post(self, request):
        serializer = PasswordResetConfirmSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = serializer.validated_data["user"]
        user.set_password(serializer.validated_data["new_password"])
        user.save(update_fields=["password"])
        return Response({"detail": "Your password has been reset. You can now log in."})


class AdminUserViewSet(
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    mixins.UpdateModelMixin,
    viewsets.GenericViewSet,
):
    # Bookings per user as a subquery: only the users on the current page are counted (lakhs of bookings).
    queryset = User.objects.annotate(booking_count=Coalesce(Subquery(
        Booking.objects.filter(user=OuterRef("pk")).order_by().values("user").annotate(c=Count("id")).values("c")[:1],
        output_field=IntegerField(),
    ), 0)).order_by("-date_joined")
    serializer_class = AdminUserSerializer
    permission_classes = [IsAdminRole]
    filterset_fields = ["role", "is_active", "is_sample"]
    search_fields = ["email", "first_name", "last_name", "phone"]

    @action(detail=False, methods=["get"], url_path="export")
    def export(self, request):
        """?kind=csv|xlsx|pdf with the same search/role/is_active filters as the list."""
        kind = request.query_params.get("kind", "xlsx")
        if kind not in ("csv", "xlsx", "pdf"):
            return Response({"detail": "kind must be csv, xlsx or pdf."}, status=status.HTTP_400_BAD_REQUEST)
        users = self.filter_queryset(self.get_queryset()).prefetch_related("assigned_museums", "partner_places")
        filters = {
            "Search": request.query_params.get("search", ""),
            "Role": request.query_params.get("role", ""),
            "Active": request.query_params.get("is_active", ""),
        }
        # Personal data leaving the system: keep a trail of who exported what.
        record(request, "users.export", user=request.user, object_repr=f"{kind} · {users.count()} users · {exports._describe(filters)}")
        if kind == "csv":
            return exports.as_csv(users)
        if kind == "pdf":
            return exports.as_pdf(users, filters)
        return exports.as_xlsx(users, filters)

    # ----------------------------------------------------------------------- place partners (read-only portal)

    @staticmethod
    def _partner_places_payload(user):
        museums = user.partner_places.select_related("city__state").order_by("name")
        return {
            "user": user.id,
            "email": user.email,
            "museums": [
                {"slug": m.slug, "name": m.name, "city_name": m.city.name, "state_name": m.city.state.name}
                for m in museums
            ],
        }

    @action(detail=True, methods=["get", "put"], url_path="partner-places")
    def partner_places(self, request, pk=None):
        """The places a partner sees in the partner portal. PUT {"museums": [slug, ...]} replaces the list."""
        from museums.models import Museum

        user = self.get_object()
        if request.method == "GET":
            return Response(self._partner_places_payload(user))
        if user.role != User.Role.PARTNER:
            return Response({"detail": "Only partner users are linked to places here. Change the role to Partner first."},
                            status=status.HTTP_400_BAD_REQUEST)
        slugs = request.data.get("museums")
        if not isinstance(slugs, list) or not all(isinstance(s, str) for s in slugs):
            return Response({"museums": ["Send a list of place slugs."]}, status=status.HTTP_400_BAD_REQUEST)
        slugs = list(dict.fromkeys(s.strip() for s in slugs if s.strip()))
        museums = list(Museum.objects.filter(slug__in=slugs))
        missing = sorted(set(slugs) - {m.slug for m in museums})
        if missing:
            return Response({"museums": [f"Unknown place(s): {', '.join(missing)}"]}, status=status.HTTP_400_BAD_REQUEST)
        user.partner_places.set(museums)
        record(request, "users.partner_places", user=request.user, object_repr=user.email,
               changes={"places": ", ".join(sorted(m.name for m in museums))})
        return Response(self._partner_places_payload(user))

    @action(detail=False, methods=["post"], url_path="partners")
    def create_partner(self, request):
        """Create a partner sign-in: {email, password, first_name?, last_name?, phone?, museums: [slug, ...]}."""
        serializer = PartnerCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = serializer.save()
        record(request, "users.create_partner", user=request.user, object_repr=user.email,
               changes={"places": ", ".join(sorted(m.name for m in user.partner_places.all()))})
        return Response(AdminUserSerializer(self.get_queryset().get(pk=user.pk)).data, status=status.HTTP_201_CREATED)
