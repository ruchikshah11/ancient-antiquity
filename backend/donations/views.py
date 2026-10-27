import csv

import django_filters
from django.conf import settings
from django.db.models import Count, Q, Sum
from django.db.models.functions import Coalesce, TruncDate
from django.http import HttpResponse
from django.utils import timezone
from django_filters.rest_framework import DjangoFilterBackend
from rest_framework import mixins, status, viewsets
from rest_framework.decorators import action, api_view, permission_classes
from rest_framework.exceptions import NotFound, ValidationError
from rest_framework.permissions import AllowAny
from rest_framework.response import Response

from accounts.permissions import IsAdminRole
from bookings.serializers import PaySerializer, RazorpayPaySerializer

from . import payments, services
from .fx import current_rates
from .models import MIN_AMOUNT, PRESET_AMOUNTS, Donation
from .serializers import AdminDonationSerializer, DonationCreateSerializer, DonationSerializer, trust_info


@api_view(["GET"])
@permission_classes([AllowAny])
def fx_rates(request):
    """GET /api/fx-rates/: approximate rates for price hints (1 INR = x units)."""
    return Response(current_rates())


def _donations():
    return Donation.objects.select_related("museum", "user")


class DonationViewSet(mixins.CreateModelMixin, mixins.RetrieveModelMixin, mixins.ListModelMixin,
                      viewsets.GenericViewSet):
    """Visitors (guests too). A donation is visible to its owner (account or email), an admin, or with
    ?token=<signed token> (returned on create and put in the receipt email link)."""

    permission_classes = [AllowAny]
    serializer_class = DonationSerializer
    lookup_field = "reference"
    lookup_value_regex = "[Aa][Dd]-[A-Za-z0-9]+"
    pagination_class = None
    filter_backends = []

    def get_queryset(self):
        return _donations()

    def list(self, request, *args, **kwargs):
        """The signed-in visitor's own donations (empty for guests)."""
        user = request.user
        if not user.is_authenticated:
            return Response([])
        qs = _donations().filter(Q(user=user) | Q(donor_email__iexact=user.email)).exclude(
            status=Donation.Status.PENDING)
        return Response(DonationSerializer(qs[:100], many=True).data)

    def _token(self):
        token = self.request.query_params.get("token")
        if not token and isinstance(self.request.data, dict):
            token = self.request.data.get("token")
        return token

    def get_object(self):
        donation = _donations().filter(reference=self.kwargs["reference"].upper()).first()
        # Strangers get the same 404 as a missing donation, so references can't be probed.
        if not donation or not services.can_view(donation, self.request.user, self._token()):
            raise NotFound("Donation not found.")
        return donation

    def _payload(self, donation, status_code=status.HTTP_200_OK):
        data = DonationSerializer(_donations().get(pk=donation.pk)).data
        data["access_token"] = services.access_token(donation)
        return Response(data, status=status_code)

    def create(self, request, *args, **kwargs):
        serializer = DonationCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = request.user if request.user.is_authenticated else None
        donation = serializer.save(user=user)
        return self._payload(donation, status.HTTP_201_CREATED)

    def retrieve(self, request, *args, **kwargs):
        return self._payload(self.get_object())

    @action(detail=False, methods=["get"])
    def info(self, request):
        """What the donate page needs: trust details, minimum, presets and the payment provider."""
        return Response({
            "trust": trust_info(),
            "min_amount": str(MIN_AMOUNT),
            "presets": list(PRESET_AMOUNTS),
            "provider": payments.provider(),
        })

    @action(detail=True, methods=["post"], url_path="payment-order")
    def payment_order(self, request, reference=None):
        donation = self.get_object()
        if donation.status == Donation.Status.PAID:
            raise ValidationError("This donation is already paid. Thank you!")
        if donation.status == Donation.Status.REFUNDED:
            raise ValidationError("This donation was refunded.")
        if payments.provider() == payments.MOCK:
            return Response({"provider": payments.MOCK})
        try:
            rz = payments.create_order(donation)
        except Exception:
            raise ValidationError("The payment gateway is not reachable right now. Please try again in a minute.")
        return Response({
            "provider": payments.RAZORPAY,
            "test_mode": payments.is_test_mode(),
            "key_id": settings.RAZORPAY_KEY_ID,
            "order_id": rz["id"],
            "amount": rz["amount"],
            "currency": rz["currency"],
            "name": trust_info()["name"],
            "description": f"Donation · {donation.purpose}"[:250],
            "prefill": {"name": donation.donor_name, "email": donation.donor_email, "contact": donation.donor_phone},
        })

    @action(detail=True, methods=["post"])
    def pay(self, request, reference=None):
        donation = self.get_object()
        if payments.provider() == payments.RAZORPAY:
            serializer = RazorpayPaySerializer(data=request.data)
            serializer.is_valid(raise_exception=True)
            data = serializer.validated_data
            if not donation.gateway_order_id or data["razorpay_order_id"] != donation.gateway_order_id:
                raise ValidationError("This payment does not belong to this donation.")
            if not payments.verify_checkout_signature(
                data["razorpay_order_id"], data["razorpay_payment_id"], data["razorpay_signature"]
            ):
                raise ValidationError("Payment could not be verified. If money was deducted it will be refunded automatically.")
            services.finalize_gateway_payment(donation.pk, data["razorpay_payment_id"])
        else:
            if donation.status not in (Donation.Status.PENDING, Donation.Status.FAILED):
                raise ValidationError(f"This donation is {donation.get_status_display().lower()}, nothing to pay.")
            serializer = PaySerializer(data=request.data)
            serializer.is_valid(raise_exception=True)
            services.mark_paid(donation, serializer.validated_data["method"])
        return self._payload(donation)

    @action(detail=True, methods=["post"])
    def failed(self, request, reference=None):
        """The browser reports a failed checkout (a later successful payment still counts)."""
        return self._payload(services.mark_failed(self.get_object()))


# --- Admin -----------------------------------------------------------------------------------------------

class AdminDonationFilter(django_filters.FilterSet):
    """?status=&museum=<slug>|general&date_from=&date_to=&wants_80g=true|false&search= (name/email/PAN/receipt)."""

    museum = django_filters.CharFilter(method="filter_museum")
    date_from = django_filters.DateFilter(field_name="day", lookup_expr="gte")
    date_to = django_filters.DateFilter(field_name="day", lookup_expr="lte")
    wants_80g = django_filters.BooleanFilter()
    status = django_filters.ChoiceFilter(choices=Donation.Status.choices)
    search = django_filters.CharFilter(method="filter_search")

    class Meta:
        model = Donation
        fields = ["status", "wants_80g"]

    def filter_museum(self, queryset, name, value):
        if value == "general":
            return queryset.filter(museum__isnull=True)
        return queryset.filter(museum__slug=value)

    def filter_search(self, queryset, name, value):
        value = value.strip()
        return queryset.filter(
            Q(donor_name__icontains=value) | Q(donor_email__icontains=value) | Q(receipt_number__icontains=value)
            | Q(reference__iexact=value) | Q(donor_pan__iexact=value)
        )


class AdminDonationViewSet(viewsets.ReadOnlyModelViewSet):
    """Admin: donations with totals (/api/admin/donations/), a Form 10BD CSV (export/) and refunds."""

    permission_classes = [IsAdminRole]
    serializer_class = AdminDonationSerializer
    lookup_field = "reference"
    filter_backends = [DjangoFilterBackend]
    filterset_class = AdminDonationFilter

    def get_queryset(self):
        # "day" = local date of payment (of creation while unpaid); the date filters use it.
        return _donations().annotate(
            day=TruncDate(Coalesce("paid_at", "created_at"), tzinfo=timezone.get_current_timezone())
        ).order_by("-created_at")

    def list(self, request, *args, **kwargs):
        qs = self.filter_queryset(self.get_queryset())
        totals = qs.aggregate(
            count=Count("id"),
            paid_count=Count("id", filter=Q(status=Donation.Status.PAID)),
            paid_amount=Sum("amount", filter=Q(status=Donation.Status.PAID)),
            paid_80g_amount=Sum("amount", filter=Q(status=Donation.Status.PAID, wants_80g=True)),
            refunded_amount=Sum("amount", filter=Q(status=Donation.Status.REFUNDED)),
        )
        for key in ("paid_amount", "paid_80g_amount", "refunded_amount"):
            totals[key] = f"{totals[key] or 0:.2f}"
        page = self.paginate_queryset(qs)
        response = self.get_paginated_response(self.get_serializer(page, many=True).data)
        response.data["totals"] = totals
        return response

    @action(detail=False, methods=["get"])
    def export(self, request):
        """CSV for the CA's Form 10BD. Only paid donations unless ?status= is given."""
        params = request.query_params.copy()
        if not params.get("status"):
            params["status"] = Donation.Status.PAID
        qs = AdminDonationFilter(params, queryset=self.get_queryset()).qs.order_by("paid_at", "id")
        response = HttpResponse(content_type="text/csv; charset=utf-8")
        response["Content-Disposition"] = f'attachment; filename="donations-10BD-{timezone.localdate():%Y%m%d}.csv"'
        response.write("﻿")  # Excel opens UTF-8 correctly with a BOM
        writer = csv.writer(response)
        writer.writerow([
            "Receipt number", "Date of donation", "Name of donor", "Address of donor", "ID code",
            "Unique identification number", "Section code", "Donation type", "Mode of receipt",
            "Amount of donation (INR)", "Payment reference", "Purpose", "Email", "Phone", "Status",
        ])
        for d in qs:
            when = timezone.localtime(d.paid_at) if d.paid_at else None
            writer.writerow([
                d.receipt_number or "", f"{when:%d-%m-%Y}" if when else "", d.donor_name, d.donor_address,
                "Permanent Account Number" if d.donor_pan else "", d.donor_pan,
                "Section 80G" if d.wants_80g else "", "Others",
                "Electronic modes including account payee cheque/draft", f"{d.amount:.2f}", d.payment_id,
                d.purpose, d.donor_email, d.donor_phone, d.get_status_display(),
            ])
        return response

    @action(detail=True, methods=["post"])
    def refund(self, request, reference=None):
        donation = self.get_object()
        try:
            services.refund(donation)
        except ValidationError:
            raise
        except Exception:
            raise ValidationError("The refund could not be started right now. Please try again.")
        return Response(AdminDonationSerializer(self.get_queryset().get(pk=donation.pk)).data)
