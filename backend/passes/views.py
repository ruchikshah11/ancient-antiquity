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
from .models import ComboPass, PassOrder
from .serializers import (
    ComboPassAdminSerializer,
    ComboPassSerializer,
    PassOrderCreateSerializer,
    PassOrderSerializer,
)


def _orders():
    return PassOrder.objects.select_related("combo_pass", "user").prefetch_related(
        "visits", "combo_pass__sites__museum__city__state"
    )


class ComboPassViewSet(viewsets.ReadOnlyModelViewSet):
    """Public: passes on sale (GET /api/passes/, /api/passes/<slug>/)."""

    permission_classes = [AllowAny]
    serializer_class = ComboPassSerializer
    lookup_field = "slug"
    pagination_class = None
    filter_backends = []

    def get_queryset(self):
        return ComboPass.objects.filter(is_active=True).prefetch_related("sites__museum__city__state")


class PassOrderViewSet(
    mixins.ListModelMixin, mixins.RetrieveModelMixin, mixins.CreateModelMixin, viewsets.GenericViewSet
):
    """The signed-in visitor's own pass orders."""

    permission_classes = [IsAuthenticated]
    serializer_class = PassOrderSerializer
    lookup_field = "reference"
    pagination_class = None
    filter_backends = []

    def get_queryset(self):
        services.expire_stale_orders()
        return _orders().filter(user=self.request.user)

    def get_object(self):
        self.kwargs["reference"] = self.kwargs["reference"].upper()
        return super().get_object()

    def create(self, request, *args, **kwargs):
        serializer = PassOrderCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = dict(serializer.validated_data)
        counts = {c: data.pop(c) for c in ("indian", "foreign", "student", "child")}
        order = services.create_order(user=request.user, counts=counts, **data)
        return Response(PassOrderSerializer(_orders().get(pk=order.pk)).data, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=["post"], url_path="payment-order")
    def payment_order(self, request, reference=None):
        order = self.get_object()
        if order.status != PassOrder.Status.PENDING:
            raise ValidationError(f"This pass is {order.get_status_display().lower()}, nothing to pay.")
        if order.is_hold_expired:
            raise ValidationError("This order expired. Please start again.")
        if payments.provider() == payments.MOCK:
            return Response({"provider": payments.MOCK})
        try:
            rz = payments.create_order(order)
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
            "description": f"{order.pass_name} · from {order.start_date:%d %b %Y}",
            "prefill": {"name": order.visitor_name, "email": order.visitor_email, "contact": order.visitor_phone},
        })

    @action(detail=True, methods=["post"])
    def pay(self, request, reference=None):
        order = self.get_object()
        if payments.provider() == payments.RAZORPAY:
            serializer = RazorpayPaySerializer(data=request.data)
            serializer.is_valid(raise_exception=True)
            data = serializer.validated_data
            if not order.gateway_order_id or data["razorpay_order_id"] != order.gateway_order_id:
                raise ValidationError("This payment does not belong to this pass.")
            if not payments.verify_checkout_signature(
                data["razorpay_order_id"], data["razorpay_payment_id"], data["razorpay_signature"]
            ):
                raise ValidationError("Payment could not be verified. If money was deducted it will be refunded automatically.")
            services.finalize_gateway_payment(
                order.pk, data["razorpay_payment_id"], payments.payment_method(data["razorpay_payment_id"])
            )
        else:
            if order.status != PassOrder.Status.PENDING:
                raise ValidationError(f"This pass is {order.get_status_display().lower()}, nothing to pay.")
            if order.is_hold_expired:
                raise ValidationError("This order expired. Please start again.")
            serializer = PaySerializer(data=request.data)
            serializer.is_valid(raise_exception=True)
            services.confirm_payment(order, serializer.validated_data["method"])
        return Response(PassOrderSerializer(_orders().get(pk=order.pk)).data)

    @action(detail=True, methods=["post"])
    def cancel(self, request, reference=None):
        order = self.get_object()
        try:
            services.cancel_order(order)
        except ValidationError:
            raise
        except Exception:
            raise ValidationError("The refund could not be started right now, so the pass was not cancelled. Please try again.")
        return Response(PassOrderSerializer(_orders().get(pk=order.pk)).data)


class AdminComboPassViewSet(viewsets.ModelViewSet):
    """Admin CRUD for combo passes (/api/admin/passes/)."""

    permission_classes = [IsAdminRole]
    serializer_class = ComboPassAdminSerializer
    pagination_class = None
    search_fields = ["name", "slug"]
    filterset_fields = ["is_active", "featured"]
    ordering_fields = ["name", "created_at"]

    def get_queryset(self):
        return ComboPass.objects.prefetch_related("sites__museum__city__state").order_by("name")

    def destroy(self, request, *args, **kwargs):
        try:
            return super().destroy(request, *args, **kwargs)
        except ProtectedError:
            raise ValidationError("This pass has been bought already. Deactivate it instead of deleting it.")


class AdminPassOrderViewSet(viewsets.ReadOnlyModelViewSet):
    """Admin: pass sales (/api/admin/pass-orders/?combo_pass__slug=&status=&search=)."""

    permission_classes = [IsAdminRole]
    serializer_class = PassOrderSerializer
    lookup_field = "reference"
    filterset_fields = {"status": ["exact"], "combo_pass__slug": ["exact"], "start_date": ["gte", "lte"]}
    search_fields = ["reference", "visitor_name", "visitor_email", "user__email"]

    def get_queryset(self):
        services.expire_stale_orders()
        return _orders()
