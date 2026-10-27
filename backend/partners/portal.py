"""Partner portal: read-only figures for a place's management (role partner, see accounts.User.partner_places).

Every query is scoped to the partner's own places and filtered by index-friendly ranges only:
`visit_date` (a DateField) by date range, `paid_at` / `cancelled_at` by datetime ranges from
ancient_antiquity.dates (never `__date` lookups, which make SQLite call a function on every row).

Definitions (the same ones settlements use):
* visitors - people on live (confirmed / checked-in) bookings whose visit date is in the period;
* revenue  - total_amount + gift-voucher part of live bookings PAID in the period;
* refunds  - refund_amount of cancelled bookings cancelled in the period.
"""
import datetime

from django.db.models import Count, Q, Sum
from django.db.models.functions import TruncDate
from django.utils import timezone
from rest_framework.exceptions import PermissionDenied
from rest_framework.response import Response
from rest_framework.views import APIView

from accounts.permissions import IsPartner
from ancient_antiquity.dates import day_range
from bookings.models import Booking
from museums.models import Museum, Review

from .models import PartnerAccount, Settlement
from .serializers import SettlementSerializer
from .services import LIVE, money

TREND_DAYS = (30, 90)


def partner_places(user):
    return Museum.objects.filter(partner_users=user)


def scoped_places(request):
    """The partner's places, or just ?museum=<slug> when given (403 for a place that isn't theirs)."""
    places = partner_places(request.user)
    slug = request.query_params.get("museum")
    if slug:
        places = places.filter(slug=slug)
        if not places.exists():
            raise PermissionDenied("This place is not linked to your partner account.")
    return places


def month_start(day):
    return day.replace(day=1)


def periods(today):
    this_month = month_start(today)
    last_month = month_start(this_month - datetime.timedelta(days=1))
    return {
        "today": (today, today),
        "this_month": (this_month, today),
        "last_month": (last_month, this_month - datetime.timedelta(days=1)),
    }


def overview(places, today):
    """Per place and in total: visitors, bookings, revenue and refunds for today / this month / last month.

    Three aggregate queries (one per measure, conditional sums per period) whatever the number of places.
    """
    spans = periods(today)
    first = spans["last_month"][0]
    place_ids = list(places.values_list("id", flat=True))
    base = Booking.objects.filter(museum_id__in=place_ids).order_by()

    visit_rows = (
        base.filter(status__in=LIVE, visit_date__gte=first, visit_date__lte=today)
        .values("museum_id")
        .annotate(**{
            f"{name}_{m}": agg(field, filter=Q(visit_date__gte=a, visit_date__lte=b))
            for name, (a, b) in spans.items()
            for m, agg, field in (("visitors", Sum, "total_visitors"), ("bookings", Count, "id"))
        })
    )
    start, end = day_range(first, today)
    paid_rows = (
        base.filter(status__in=LIVE, paid_at__gte=start, paid_at__lt=end)
        .values("museum_id")
        .annotate(**{
            f"{name}_{m}": Sum(field, filter=Q(paid_at__gte=day_range(a, b)[0], paid_at__lt=day_range(a, b)[1]))
            for name, (a, b) in spans.items()
            for m, field in (("amount", "total_amount"), ("voucher", "voucher_amount"))
        })
    )
    refund_rows = (
        base.filter(status=Booking.Status.CANCELLED, refund_amount__gt=0, cancelled_at__gte=start, cancelled_at__lt=end)
        .values("museum_id")
        .annotate(**{
            f"{name}_refunds": Sum(
                "refund_amount", filter=Q(cancelled_at__gte=day_range(a, b)[0], cancelled_at__lt=day_range(a, b)[1])
            )
            for name, (a, b) in spans.items()
        })
    )
    by_place = {}
    for rows in (visit_rows, paid_rows, refund_rows):
        for r in rows:
            by_place.setdefault(r["museum_id"], {}).update(r)

    def figures(row):
        return {
            name: {
                "visitors": row.get(f"{name}_visitors") or 0,
                "bookings": row.get(f"{name}_bookings") or 0,
                "revenue": money((row.get(f"{name}_amount") or 0) + (row.get(f"{name}_voucher") or 0)),
                "refunds": money(row.get(f"{name}_refunds") or 0),
            }
            for name in spans
        }

    out, totals = [], {name: {"visitors": 0, "bookings": 0, "revenue": money(0), "refunds": money(0)} for name in spans}
    for m in places.select_related("city").order_by("name"):
        f = figures(by_place.get(m.id, {}))
        for name, values in f.items():
            for key, value in values.items():
                totals[name][key] += value
        out.append({"slug": m.slug, "name": m.name, "city_name": m.city.name, "place_type": m.place_type, **f})
    return {
        "date": today,
        "periods": {name: {"from": a, "to": b} for name, (a, b) in spans.items()},
        "places": out,
        "totals": totals,
    }


def daily_trend(places, today, days):
    """Visitors per visit day and revenue per payment day, oldest first, every day present (zeros included)."""
    first = today - datetime.timedelta(days=days - 1)
    base = Booking.objects.filter(museum__in=places, status__in=LIVE).order_by()
    visitors = dict(
        base.filter(visit_date__gte=first, visit_date__lte=today)
        .values("visit_date").annotate(n=Sum("total_visitors")).values_list("visit_date", "n")
    )
    start, end = day_range(first, today)
    revenue = {
        r["day"]: (r["a"] or 0) + (r["v"] or 0)
        for r in base.filter(paid_at__gte=start, paid_at__lt=end)
        .annotate(day=TruncDate("paid_at")).values("day").annotate(a=Sum("total_amount"), v=Sum("voucher_amount"))
    }
    out = []
    for i in range(days):
        day = first + datetime.timedelta(days=i)
        out.append({"date": day, "visitors": visitors.get(day) or 0, "revenue": money(revenue.get(day))})
    return out


class PartnerMeView(APIView):
    """GET /api/partner/me/: the places linked to this partner."""

    permission_classes = [IsPartner]

    def get(self, request):
        return Response({
            "email": request.user.email,
            "places": [
                {"slug": m.slug, "name": m.name, "city_name": m.city.name, "state_name": m.city.state.name,
                 "place_type": m.place_type, "image_url": m.image_url}
                for m in partner_places(request.user).select_related("city__state").order_by("name")
            ],
        })


class PartnerOverviewView(APIView):
    """GET /api/partner/overview/[?museum=<slug>]: KPIs per place for today, this month and last month."""

    permission_classes = [IsPartner]

    def get(self, request):
        return Response(overview(scoped_places(request), timezone.localdate()))


class PartnerTrendView(APIView):
    """GET /api/partner/trend/?days=30|90[&museum=<slug>]: daily visitors and revenue."""

    permission_classes = [IsPartner]

    def get(self, request):
        try:
            days = int(request.query_params.get("days", 30))
        except (TypeError, ValueError):
            days = 30
        days = days if days in TREND_DAYS else 30
        today = timezone.localdate()
        return Response({"days": days, "daily": daily_trend(scoped_places(request), today, days)})


class PartnerReviewsView(APIView):
    """GET /api/partner/reviews/[?museum=<slug>&offset=&limit=]: newest published reviews of their places."""

    permission_classes = [IsPartner]

    def get(self, request):
        def int_param(name, default, low, high):
            try:
                return min(max(int(request.query_params.get(name, default)), low), high)
            except (TypeError, ValueError):
                return default

        offset, limit = int_param("offset", 0, 0, 10**6), int_param("limit", 10, 1, 50)
        # One place at a time walks review_place_published_idx; several places merge their index ranges.
        qs = Review.objects.filter(museum__in=scoped_places(request), is_published=True)
        total = qs.count()
        page = qs.select_related("museum", "user").order_by("-created_at", "-id")[offset:offset + limit]
        from museums.serializers import ReviewSerializer

        name_of = ReviewSerializer().get_user_name
        return Response({
            "count": total,
            "next_offset": offset + limit if offset + limit < total else None,
            "results": [
                {"id": r.id, "museum_slug": r.museum.slug, "museum_name": r.museum.name, "rating": float(r.rating),
                 "title": r.title, "comment": r.comment, "user_name": name_of(r), "helpful_count": r.helpful_count,
                 "created_at": r.created_at}
                for r in page
            ],
        })


class PartnerSettlementsView(APIView):
    """GET /api/partner/settlements/[?museum=<slug>]: approved and paid settlements (payouts) of their places.

    Drafts are left out: they are still being checked and may change.
    """

    permission_classes = [IsPartner]

    def get(self, request):
        places = scoped_places(request)
        qs = list(
            Settlement.objects.filter(museum__in=places, status__in=[Settlement.Status.APPROVED, Settlement.Status.PAID])
            .select_related("museum__city", "approved_by", "created_by").order_by("-period_end", "museum__name")[:200]
        )
        accounts = {
            a.museum_id: {"bank_name": a.bank_name, "account_number": a.masked_account_number}
            for a in PartnerAccount.objects.filter(museum__in=places)
        }
        data = []
        for s, row in zip(qs, SettlementSerializer(qs, many=True).data):
            # Internal names of who approved/generated it are not the partner's business.
            row.pop("approved_by_email", None)
            row.pop("created_by_email", None)
            row["payout_account"] = accounts.get(s.museum_id)
            data.append(row)
        return Response({"results": data})
