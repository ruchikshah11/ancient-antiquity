from django.utils import timezone
from rest_framework.exceptions import NotFound, PermissionDenied, ValidationError
from rest_framework.response import Response
from rest_framework.views import APIView

from accounts.permissions import IsPanelUser
from museums.models import Museum

from . import services


class PricingSuggestionsView(APIView):
    """GET /api/admin/pricing-suggestions/?museum=<slug>&weeks=12[&elasticity=0.5]

    Panel users; staff only for the places assigned to them (like the other admin views).
    Rules are created with the existing price-rule API (POST /api/admin/price-rules/, administrators).
    """

    permission_classes = [IsPanelUser]

    def get(self, request):
        params = request.query_params
        slug = (params.get("museum") or "").strip()
        if not slug:
            raise ValidationError({"museum": "Choose a place."})
        museum = Museum.objects.filter(slug=slug).first()
        if not museum:
            raise NotFound("Place not found.")
        if not Museum.for_panel_user(request.user).filter(pk=museum.pk).exists():
            raise PermissionDenied("You are not assigned to this museum.")
        try:
            weeks = min(max(int(params.get("weeks", 12)), 2), 52)
        except (TypeError, ValueError):
            raise ValidationError({"weeks": "Use a number of weeks between 2 and 52."})
        try:
            elasticity = min(max(float(params.get("elasticity", services.DEFAULT_ELASTICITY)), 0.0), 3.0)
        except (TypeError, ValueError):
            raise ValidationError({"elasticity": "Use a number such as 0.5."})
        data = services.pricing_suggestions(museum, timezone.localdate(), weeks=weeks, elasticity=elasticity)
        data["can_create_rules"] = request.user.is_admin_role
        return Response(data)
