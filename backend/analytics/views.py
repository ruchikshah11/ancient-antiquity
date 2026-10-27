import datetime
import re

from django.db.models import Count, Q
from django.db.models.functions import TruncDate
from django.http import HttpResponse
from django.utils import timezone
from django.utils.html import escape
from rest_framework import permissions, status
from rest_framework.response import Response
from rest_framework.throttling import SimpleRateThrottle
from rest_framework.views import APIView

from accounts.permissions import IsPanelUser
from bookings.models import Booking
from bookings.reports import report_filters
from museums.models import Museum
from ancient_antiquity.dates import day_range

from .models import EmailOptOut, FunnelEvent, RecoveryEmail
from .recovery import email_from_token, mark_conversions

MAX_EVENTS_PER_REQUEST = 20
DEDUPE_WINDOW = datetime.timedelta(minutes=30)
SESSION_RE = re.compile(r"^[A-Za-z0-9_-]{8,64}$")
BOT_RE = re.compile(
    r"bot|crawl|spider|slurp|headless|lighthouse|pagespeed|preview|facebookexternalhit|curl|wget|python-requests|"
    r"httpclient|monitor|uptime",
    re.I,
)
CLIENT_EVENTS = {
    FunnelEvent.Event.VIEW_PLACE, FunnelEvent.Event.SELECT_SLOT, FunnelEvent.Event.START_BOOKING,
    FunnelEvent.Event.VIEW_CHECKOUT, FunnelEvent.Event.PAYMENT_STARTED, FunnelEvent.Event.PAID,
    FunnelEvent.Event.CANCELLED,
}
PAID = [Booking.Status.CONFIRMED, Booking.Status.CHECKED_IN]


class FunnelEventThrottle(SimpleRateThrottle):
    """Per client IP; events arrive in small batches, so this is generous for people and tight for scripts."""

    scope = "funnel_events"
    rate = "60/min"

    def get_cache_key(self, request, view):
        return self.cache_format % {"scope": self.scope, "ident": self.get_ident(request)}


def is_bot(request):
    ua = request.META.get("HTTP_USER_AGENT", "")
    return not ua or bool(BOT_RE.search(ua))


def _clip(value, n):
    return str(value or "")[:n]


class FunnelEventView(APIView):
    """POST /api/analytics/events/ {session_id, events: [{event, museum?, booking?}], utm?: {source, medium, campaign}}.

    Fire-and-forget from the website: always answers 202, silently ignoring bots, staff/admins and bad entries.
    """

    permission_classes = [permissions.AllowAny]
    throttle_classes = [FunnelEventThrottle]

    def post(self, request):
        data = request.data if isinstance(request.data, dict) else {}
        user = request.user if request.user and request.user.is_authenticated else None
        session_id = str(data.get("session_id") or "")
        if is_bot(request) or (user is not None and user.is_panel_user) or not SESSION_RE.match(session_id):
            return Response({"recorded": 0}, status=status.HTTP_202_ACCEPTED)
        events = data.get("events")
        if not isinstance(events, list):
            events = [data] if data.get("event") else []
        utm = data.get("utm") if isinstance(data.get("utm"), dict) else {}

        museum_cache, recorded, since = {}, 0, timezone.now() - DEDUPE_WINDOW
        for item in events[:MAX_EVENTS_PER_REQUEST]:
            if not isinstance(item, dict) or item.get("event") not in CLIENT_EVENTS:
                continue
            slug = _clip(item.get("museum"), 170)
            museum = None
            if slug:
                if slug not in museum_cache:
                    museum_cache[slug] = Museum.objects.filter(slug=slug).only("id").first()
                museum = museum_cache[slug]
            booking = None
            ref = _clip(item.get("booking"), 12)
            if ref and user is not None:  # only the visitor's own booking can be linked
                booking = Booking.objects.filter(reference=ref, user=user).only("id", "museum_id").first()
                if booking and museum is None:
                    museum = Museum(pk=booking.museum_id)
            # Reloads and double mounts send the same step again: keep one per session/step/place/booking.
            if FunnelEvent.objects.filter(
                session_id=session_id, event=item["event"], museum=museum, booking=booking, created_at__gte=since
            ).exists():
                continue
            FunnelEvent.objects.create(
                session_id=session_id, user=user, event=item["event"], museum=museum, booking=booking,
                utm_source=_clip(utm.get("source"), 60), utm_medium=_clip(utm.get("medium"), 60),
                utm_campaign=_clip(utm.get("campaign"), 80),
            )
            recorded += 1
        return Response({"recorded": recorded}, status=status.HTTP_202_ACCEPTED)


UNSUBSCRIBE_PAGE = """<!DOCTYPE html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1"><title>{title}</title></head>
<body style="font-family:Arial,Helvetica,sans-serif;background:#f1f5f9;color:#1e293b;margin:0;padding:48px 16px;">
<div style="max-width:520px;margin:0 auto;background:#fff;border-radius:8px;padding:28px;">
<h1 style="font-size:20px;margin:0 0 12px;">{title}</h1><p style="margin:0 0 16px;">{body}</p>
<a href="/" style="color:#0277bd;">Back to Ancient Antiquity</a></div></body></html>"""


class UnsubscribeView(APIView):
    """GET (link in the email) or POST (one-click List-Unsubscribe) /api/analytics/unsubscribe/<token>/."""

    permission_classes = [permissions.AllowAny]
    authentication_classes = []

    def _handle(self, token):
        email = email_from_token(token)
        if not email:
            html = UNSUBSCRIBE_PAGE.format(title="Link not valid",
                                           body="This unsubscribe link is broken or incomplete.")
            return HttpResponse(html, status=400)
        EmailOptOut.objects.get_or_create(email=email.strip().lower())
        html = UNSUBSCRIBE_PAGE.format(
            title="You're unsubscribed",
            body=f"We won't send booking reminders to {escape(email)} again. Your tickets and booking "
                 f"confirmations are not affected.",
        )
        return HttpResponse(html)

    def get(self, request, token):
        return self._handle(token)

    def post(self, request, token):
        return self._handle(token)


def _pct(part, whole):
    return round(part * 100.0 / whole, 1) if whole else None


class FunnelReportView(APIView):
    """GET /api/admin/funnel/?from=&to=&museum= - staff see only their assigned places."""

    permission_classes = [IsPanelUser]

    def get(self, request):
        bookings, date_from, date_to, museum = report_filters(request)
        user = request.user
        start, end = day_range(date_from, date_to)
        events = FunnelEvent.objects.filter(created_at__gte=start, created_at__lt=end)
        if museum is not None:
            events = events.filter(museum=museum)
        elif not user.is_admin_role:
            events = events.filter(museum__in=Museum.for_panel_user(user))
        online = bookings.filter(channel=Booking.Channel.ONLINE, is_group=False)

        def sessions(event):
            return events.filter(event=event).values("session_id").distinct().count()

        paid_q = Q(paid_at__isnull=False) | Q(status__in=PAID)
        steps_raw = [
            ("view_place", "Viewed a place", sessions(FunnelEvent.Event.VIEW_PLACE), "sessions"),
            ("select_slot", "Selected a slot", sessions(FunnelEvent.Event.SELECT_SLOT), "sessions"),
            ("start_booking", "Started a booking", online.count(), "bookings"),
            ("view_checkout", "Opened checkout", sessions(FunnelEvent.Event.VIEW_CHECKOUT), "sessions"),
            ("payment_started", "Started payment",
             online.filter(Q(gateway_order_id__gt="") | paid_q).count(), "bookings"),
            ("paid", "Paid", online.filter(paid_q).count(), "bookings"),
        ]
        first = steps_raw[0][2]
        steps, prev = [], None
        for key, label, count, source in steps_raw:
            steps.append({
                "key": key, "label": label, "count": count, "source": source,
                "pct_of_first": _pct(count, first),
                "pct_of_previous": _pct(count, prev) if prev is not None else None,
            })
            prev = count

        # Top places: sessions that viewed the place vs paid online bookings for it.
        views_by_place = {
            r["museum"]: r["n"] for r in events.filter(event=FunnelEvent.Event.VIEW_PLACE, museum__isnull=False)
            .values("museum").annotate(n=Count("session_id", distinct=True)).order_by()
        }
        paid_by_place = {
            r["museum"]: r["n"] for r in online.filter(paid_q).values("museum").annotate(n=Count("id")).order_by()
        }
        place_ids = set(views_by_place) | set(paid_by_place)
        names = {m.id: m for m in Museum.objects.filter(id__in=place_ids).select_related("city")}
        places = []
        for pid in place_ids:
            m = names.get(pid)
            if m is None:
                continue
            views, paid = views_by_place.get(pid, 0), paid_by_place.get(pid, 0)
            places.append({"slug": m.slug, "name": m.name, "city": m.city.name, "views": views, "paid": paid,
                           "conversion": _pct(paid, views)})
        places.sort(key=lambda p: (p["conversion"] if p["conversion"] is not None else -1, p["views"], p["paid"]),
                    reverse=True)

        # Recovery emails sent in the range (and conversions within 7 days of each email).
        recoveries = RecoveryEmail.objects.filter(sent_at__date__gte=date_from, sent_at__date__lte=date_to)
        if museum is not None:
            recoveries = recoveries.filter(booking__museum=museum)
        elif not user.is_admin_role:
            recoveries = recoveries.filter(booking__museum__in=Museum.for_panel_user(user))
        mark_conversions(recoveries)
        sent = recoveries.count()
        converted = recoveries.filter(converted_booking__isnull=False).count()

        # Daily trend.
        views_day = {
            r["day"]: r["n"] for r in events.filter(event=FunnelEvent.Event.VIEW_PLACE)
            .annotate(day=TruncDate("created_at")).values("day").annotate(n=Count("session_id", distinct=True)).order_by()
        }
        started_day = {
            r["day"]: r["n"] for r in online.annotate(day=TruncDate("created_at")).values("day")
            .annotate(n=Count("id")).order_by()
        }
        paid_day = {
            r["day"]: r["n"] for r in online.filter(paid_q).annotate(day=TruncDate("created_at")).values("day")
            .annotate(n=Count("id")).order_by()
        }
        daily, day = [], date_from
        while day <= date_to:
            daily.append({"date": day, "views": views_day.get(day, 0), "started": started_day.get(day, 0),
                          "paid": paid_day.get(day, 0)})
            day += datetime.timedelta(days=1)

        return Response({
            "from": date_from,
            "to": date_to,
            "museum": {"slug": museum.slug, "name": museum.name} if museum else None,
            "steps": steps,
            "overall_conversion": _pct(steps[-1]["count"], first),
            "cancelled": online.filter(status=Booking.Status.CANCELLED).count(),
            "abandoned": online.filter(status=Booking.Status.EXPIRED, paid_at__isnull=True).count(),
            "top_places": places[:10],
            "recovery": {"sent": sent, "converted": converted, "conversion": _pct(converted, sent)},
            "daily": daily,
        })
