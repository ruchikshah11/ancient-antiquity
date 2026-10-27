import datetime

from django.db.models import Q
from django.utils import timezone
from django.utils.dateparse import parse_date, parse_datetime
from rest_framework import generics, serializers
from rest_framework.pagination import PageNumberPagination

from accounts.permissions import IsAdminRole

from .models import AuditEntry


class AuditEntrySerializer(serializers.ModelSerializer):
    user_email = serializers.EmailField(source="user.email", read_only=True, default=None)
    user_name = serializers.SerializerMethodField()

    class Meta:
        model = AuditEntry
        fields = (
            "id", "at", "user", "user_email", "user_name", "ip", "method", "path",
            "action", "object_repr", "status_code", "changes",
        )
        read_only_fields = fields

    def get_user_name(self, obj):
        return obj.user.get_full_name() if obj.user else ""


class AuditPagination(PageNumberPagination):
    page_size = 25
    page_size_query_param = "page_size"
    max_page_size = 200


def _bound(value, end=False):
    """Accept YYYY-MM-DD (whole day) or an ISO datetime."""
    if not value:
        return None
    moment = parse_datetime(value)
    if moment is None:
        day = parse_date(value)
        if day is None:
            return None
        moment = datetime.datetime.combine(day, datetime.time.max if end else datetime.time.min)
    if timezone.is_naive(moment):
        moment = timezone.make_aware(moment)
    return moment


class AuditEntryListView(generics.ListAPIView):
    """GET /api/admin/audit/?user=<id|email>&action=&from=&to=&search= (administrators only)."""

    serializer_class = AuditEntrySerializer
    permission_classes = [IsAdminRole]
    pagination_class = AuditPagination
    filter_backends = []  # filtering is done by hand below

    def get_queryset(self):
        qs = AuditEntry.objects.select_related("user")
        p = self.request.query_params
        user = (p.get("user") or "").strip()
        if user:
            qs = qs.filter(user_id=user) if user.isdigit() else qs.filter(user__email__icontains=user)
        action = (p.get("action") or "").strip()
        if action:
            qs = qs.filter(action__in=[a for a in action.split(",") if a])
        start, end = _bound(p.get("from")), _bound(p.get("to"), end=True)
        if start:
            qs = qs.filter(at__gte=start)
        if end:
            qs = qs.filter(at__lte=end)
        search = (p.get("search") or "").strip()
        if search:
            qs = qs.filter(
                Q(path__icontains=search) | Q(object_repr__icontains=search)
                | Q(user__email__icontains=search) | Q(ip__icontains=search)
            )
        return qs
