from django.db.models import ProtectedError
from django.shortcuts import get_object_or_404
from django.utils.dateparse import parse_date
from rest_framework import viewsets
from rest_framework.exceptions import ValidationError
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from accounts.permissions import IsAdminRole, IsPanelUser
from museums.models import Museum

from . import services
from .models import AddOn
from .serializers import AddOnAdminSerializer, AddOnSerializer


class MuseumAddOnsView(APIView):
    """Public: GET /api/museums/<slug>/addons/[?date=YYYY-MM-DD] -> the place's active add-ons.

    With a date, each add-on that has a daily stock also says how many are left that day (`remaining`).
    The same list doubles as the "What you can add" chips on the place page (name + icon).
    """

    permission_classes = [AllowAny]

    def get(self, request, slug):
        museum = get_object_or_404(Museum, slug=slug, is_active=True)
        addons = list(museum.addons.filter(is_active=True))
        day = parse_date(request.query_params.get("date", "") or "")
        remaining = {}
        if day:
            # ?booking=<reference>: the caller's own pending booking doesn't count against what it can still take.
            own = _own_booking(request, request.query_params.get("booking") or "")
            for a in addons:
                if a.daily_stock is not None:
                    remaining[a.id] = services.remaining_on(a, day, exclude_booking=own)
        return Response(AddOnSerializer(addons, many=True, context={"remaining": remaining}).data)


def _own_booking(request, reference):
    """The caller's booking with this reference (its own add-ons don't count against the stock it sees)."""
    from bookings.models import Booking

    if not reference or not request.user.is_authenticated:
        return None
    return Booking.objects.filter(reference=reference.upper(), user=request.user).first()


class AdminAddOnViewSet(viewsets.ModelViewSet):
    """Add-ons per place: /api/admin/addons/?museum=<slug>. Staff read their assigned places; admins edit."""

    serializer_class = AddOnAdminSerializer
    pagination_class = None
    filter_backends = []

    def get_permissions(self):
        return [IsPanelUser()] if self.action in ("list", "retrieve") else [IsAdminRole()]

    def get_queryset(self):
        qs = AddOn.objects.select_related("museum").filter(museum__in=Museum.for_panel_user(self.request.user))
        slug = self.request.query_params.get("museum")
        return qs.filter(museum__slug=slug) if slug else qs.order_by("museum__name", "sort", "id")

    def destroy(self, request, *args, **kwargs):
        try:
            return super().destroy(request, *args, **kwargs)
        except ProtectedError:
            raise ValidationError("This add-on has been sold already. Switch it off instead of deleting it.")
