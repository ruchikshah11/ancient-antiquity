from django.conf import settings
from django.db.models import ProtectedError
from rest_framework import mixins, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response

from accounts.permissions import IsAdminRole
from bookings.serializers import PaySerializer, RazorpayPaySerializer

from . import payments, services
from .models import Membership, MembershipPlan
from .serializers import (
    MembershipCreateSerializer,
    MembershipPlanAdminSerializer,
    MembershipPlanSerializer,
    MembershipSerializer,
)


def _memberships():
    return Membership.objects.select_related("plan", "user").prefetch_related("plan__places")


class MembershipPlanViewSet(viewsets.ReadOnlyModelViewSet):
    """Public: plans on sale (GET /api/membership-plans/, /api/membership-plans/<slug>/)."""

    permission_classes = [AllowAny]
    serializer_class = MembershipPlanSerializer
    lookup_field = "slug"
    pagination_class = None
    filter_backends = []

    def get_queryset(self):
        return MembershipPlan.objects.filter(is_active=True).prefetch_related("places__city")


class MembershipViewSet(
    mixins.ListModelMixin, mixins.RetrieveModelMixin, mixins.CreateModelMixin, viewsets.GenericViewSet
):
    """The signed-in visitor's own Heritage Cards (/api/memberships/, lookup by card number)."""

    permission_classes = [IsAuthenticated]
    serializer_class = MembershipSerializer
    lookup_field = "card_number"
    pagination_class = None
    filter_backends = []

    def get_queryset(self):
        services.expire_stale()
        return _memberships().filter(user=self.request.user)

    def get_object(self):
        self.kwargs["card_number"] = self.kwargs["card_number"].upper()
        return super().get_object()

    def create(self, request, *args, **kwargs):
        serializer = MembershipCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        membership = services.create_membership(user=request.user, **serializer.validated_data)
        return Response(MembershipSerializer(_memberships().get(pk=membership.pk)).data, status=status.HTTP_201_CREATED)

    @action(detail=False, methods=["get"])
    def current(self, request):
        """The card valid today, or {"membership": null} (Profile prompt)."""
        services.expire_stale()
        card = services.current_for(request.user)
        return Response({"membership": MembershipSerializer(card).data if card else None})

    @action(detail=True, methods=["post"], url_path="payment-order")
    def payment_order(self, request, card_number=None):
        membership = self.get_object()
        if membership.status != Membership.Status.PENDING:
            raise ValidationError(f"This membership is {membership.get_status_display().lower()}, nothing to pay.")
        if membership.is_hold_expired:
            raise ValidationError("This purchase expired. Please start again.")
        if payments.provider() == payments.MOCK:
            return Response({"provider": payments.MOCK})
        try:
            rz = payments.create_order(membership)
        except Exception:
            raise ValidationError("The payment gateway is not reachable right now. Please try again in a minute.")
        return Response({
            "provider": payments.RAZORPAY,
            "test_mode": payments.is_test_mode(),
            "key_id": settings.RAZORPAY_KEY_ID,
            "order_id": rz["id"],
            "amount": rz["amount"],
            "currency": rz["currency"],
            "name": "Ancient Antiquity",
            "description": f"{membership.plan_name} · {membership.duration_days} days",
            "prefill": {"name": membership.holder_name, "email": request.user.email, "contact": request.user.phone},
        })

    @action(detail=True, methods=["post"])
    def pay(self, request, card_number=None):
        membership = self.get_object()
        if payments.provider() == payments.RAZORPAY:
            serializer = RazorpayPaySerializer(data=request.data)
            serializer.is_valid(raise_exception=True)
            data = serializer.validated_data
            if not membership.gateway_order_id or data["razorpay_order_id"] != membership.gateway_order_id:
                raise ValidationError("This payment does not belong to this membership.")
            if not payments.verify_checkout_signature(
                data["razorpay_order_id"], data["razorpay_payment_id"], data["razorpay_signature"]
            ):
                raise ValidationError("Payment could not be verified. If money was deducted it will be refunded automatically.")
            services.finalize_gateway_payment(
                membership.pk, data["razorpay_payment_id"], payments.payment_method(data["razorpay_payment_id"])
            )
        else:
            if membership.status != Membership.Status.PENDING:
                raise ValidationError(f"This membership is {membership.get_status_display().lower()}, nothing to pay.")
            if membership.is_hold_expired:
                raise ValidationError("This purchase expired. Please start again.")
            serializer = PaySerializer(data=request.data)
            serializer.is_valid(raise_exception=True)
            services.confirm_payment(membership, serializer.validated_data["method"])
        return Response(MembershipSerializer(_memberships().get(pk=membership.pk)).data)


class AdminMembershipPlanViewSet(viewsets.ModelViewSet):
    """Admin CRUD for plans (/api/admin/membership-plans/)."""

    permission_classes = [IsAdminRole]
    serializer_class = MembershipPlanAdminSerializer
    pagination_class = None
    filter_backends = []

    def get_queryset(self):
        return MembershipPlan.objects.prefetch_related("places__city").order_by("sort", "price", "id")

    def destroy(self, request, *args, **kwargs):
        try:
            return super().destroy(request, *args, **kwargs)
        except ProtectedError:
            raise ValidationError("Cards have been bought on this plan. Take it off sale instead of deleting it.")


class AdminMembershipViewSet(viewsets.ReadOnlyModelViewSet):
    """Admin: cards sold (/api/admin/memberships/?search=<email or card>&status=&plan__slug=) and cancel."""

    permission_classes = [IsAdminRole]
    serializer_class = MembershipSerializer
    lookup_field = "card_number"
    filterset_fields = {"status": ["exact"], "plan__slug": ["exact"]}
    search_fields = ["card_number", "user__email", "holder_name"]
    ordering_fields = ["created_at", "ends_on"]

    def get_queryset(self):
        services.expire_stale()
        return _memberships()

    @action(detail=True, methods=["post"])
    def cancel(self, request, card_number=None):
        """Cancel a card; {"refund": true} also refunds the full price to the original payment."""
        membership = self.get_object()
        refund = str(request.data.get("refund", "")).lower() in ("1", "true", "yes")
        try:
            services.cancel_membership(membership, refund=refund)
        except ValidationError:
            raise
        except Exception:
            raise ValidationError("The refund could not be started right now, so the card was not cancelled. Please try again.")
        return Response(MembershipSerializer(_memberships().get(pk=membership.pk)).data)
