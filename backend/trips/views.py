from django.db import transaction
from django.db.models import Avg, Count, FloatField, IntegerField, Max, OuterRef, Q, Subquery
from django.db.models.functions import Coalesce
from django.shortcuts import get_object_or_404
from rest_framework import permissions, serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.views import APIView

from museums.models import Museum, Review
from museums.serializers import MuseumListSerializer

from .geo import haversine_km, located_places
from .models import MAX_STOPS_PER_TRIP, MAX_TRIP_DAYS, Favourite, Trip, TripStop
from .serializers import TripDetailSerializer, TripListSerializer, TripStopSerializer, serialize_stops

VALID_TYPES = {choice for choice, _ in Museum.PlaceType.choices}


def _types(request):
    raw = request.query_params.get("type", "")
    return [t for t in raw.split(",") if t in VALID_TYPES]


def _float(request, name, default=None, low=None, high=None):
    raw = request.query_params.get(name)
    if raw in (None, ""):
        if default is None:
            raise serializers.ValidationError({name: "This parameter is required."})
        return default
    try:
        value = float(raw)
    except ValueError:
        raise serializers.ValidationError({name: "Must be a number."})
    if value != value or (low is not None and value < low) or (high is not None and value > high):  # NaN or out of range
        raise serializers.ValidationError({name: f"Must be between {low} and {high}."})
    return value


class GeoPlacesView(APIView):
    """GET /api/places/geo/ - every active place that can be pinned on the map (compact, public)."""

    permission_classes = [permissions.AllowAny]

    def get(self, request):
        return Response(located_places(_types(request)))


class NearbyPlacesView(APIView):
    """GET /api/places/nearby/?lat=&lng=&radius_km=50&type=&limit= - places sorted by distance."""

    permission_classes = [permissions.AllowAny]

    def get(self, request):
        lat = _float(request, "lat", low=-90, high=90)
        lng = _float(request, "lng", low=-180, high=180)
        radius = _float(request, "radius_km", default=50, low=1, high=5000)
        limit = int(_float(request, "limit", default=50, low=1, high=300))
        rows = []
        for place in located_places(_types(request)):
            distance = haversine_km(lat, lng, place["lat"], place["lng"])
            if distance <= radius:
                rows.append({**place, "distance_km": round(distance, 1)})
        rows.sort(key=lambda r: (r["distance_km"], r["name"]))
        return Response({"count": len(rows), "radius_km": radius, "results": rows[:limit]})


# ------------------------------------------------------------------ favourites

def _annotated_places():
    return (
        Museum.objects.select_related("city__state", "category", "info_verified_by")
        .prefetch_related("ticket_types")
        .annotate(
            avg_rating=Subquery(
                Review.objects.filter(museum=OuterRef("pk"), is_published=True).order_by()
                .values("museum").annotate(a=Avg("rating")).values("a")[:1],
                output_field=FloatField(),
            ),
            review_count=Coalesce(Subquery(
                Review.objects.filter(museum=OuterRef("pk"), is_published=True).order_by()
                .values("museum").annotate(c=Count("id")).values("c")[:1],
                output_field=IntegerField(),
            ), 0),
        )
    )


class FavouriteListView(APIView):
    """GET: my saved places (newest first). POST {museum: slug}: save one (idempotent)."""

    def get(self, request):
        favourites = list(
            Favourite.objects.filter(user=request.user, museum__is_active=True).values_list("museum_id", "created_at")
        )
        places = {m.id: m for m in _annotated_places().filter(id__in=[f[0] for f in favourites])}
        context = {"request": request}
        return Response([
            {"created_at": created, "museum": MuseumListSerializer(places[mid], context=context).data}
            for mid, created in favourites
            if mid in places
        ])

    def post(self, request):
        slug = request.data.get("museum") or request.data.get("slug")
        if not slug or not isinstance(slug, str):
            raise serializers.ValidationError({"museum": "Choose a place."})
        museum = get_object_or_404(Museum, slug=slug, is_active=True)
        _, created = Favourite.objects.get_or_create(user=request.user, museum=museum)
        return Response(
            {"slug": museum.slug, "favourite": True}, status=status.HTTP_201_CREATED if created else status.HTTP_200_OK
        )


class FavouriteDetailView(APIView):
    def delete(self, request, slug):
        Favourite.objects.filter(user=request.user, museum__slug=slug).delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


class FavouriteIdsView(APIView):
    """Slugs only, so place cards can show filled hearts with one request."""

    def get(self, request):
        return Response(list(Favourite.objects.filter(user=request.user).values_list("museum__slug", flat=True)))


# ------------------------------------------------------------------ trips

def _next_order(trip, day):
    last = trip.stops.filter(day=day).aggregate(m=Max("order"))["m"]
    return 0 if last is None else last + 1


class TripViewSet(viewsets.ModelViewSet):
    """Owner-only trip planner. Stops are managed through the nested actions below."""

    pagination_class = None

    def get_queryset(self):
        return Trip.objects.filter(user=self.request.user).annotate(stop_count=Count("stops"))

    def get_serializer_class(self):
        return TripListSerializer if self.action == "list" else TripDetailSerializer

    def perform_create(self, serializer):
        serializer.save(user=self.request.user)

    @transaction.atomic
    def perform_update(self, serializer):
        trip = serializer.save()
        days = trip.day_count
        if days:  # trip got shorter: stops from later days move to the end of the new last day
            order = _next_order(trip, days)
            for stop in trip.stops.filter(day__gt=days).order_by("day", "order", "id"):
                stop.day, stop.order = days, order
                stop.save(update_fields=["day", "order"])
                order += 1

    def _context(self, trip):
        return {**self.get_serializer_context(), "trip": trip}

    @action(detail=True, methods=["post"])
    def stops(self, request, pk=None):
        trip = self.get_object()
        if trip.stops.count() >= MAX_STOPS_PER_TRIP:
            raise serializers.ValidationError({"detail": f"A trip can have at most {MAX_STOPS_PER_TRIP} stops."})
        serializer = TripStopSerializer(data=request.data, context=self._context(trip))
        serializer.is_valid(raise_exception=True)
        stop = serializer.save(trip=trip, order=_next_order(trip, serializer.validated_data.get("day", 1)))
        trip.save(update_fields=["updated_at"])
        return Response(serialize_stops(stop, self._context(trip), many=False), status=status.HTTP_201_CREATED)

    @action(detail=True, methods=["patch", "delete"], url_path=r"stops/(?P<stop_id>\d+)")
    def stop(self, request, pk=None, stop_id=None):
        trip = self.get_object()
        stop = get_object_or_404(TripStop, pk=stop_id, trip=trip)
        if request.method == "DELETE":
            stop.delete()
            trip.save(update_fields=["updated_at"])
            return Response(status=status.HTTP_204_NO_CONTENT)
        old_day = stop.day
        serializer = TripStopSerializer(stop, data=request.data, partial=True, context=self._context(trip))
        serializer.is_valid(raise_exception=True)
        new_day = serializer.validated_data.get("day", old_day)
        extra = {"order": _next_order(trip, new_day)} if new_day != old_day else {}  # moved: goes last on that day
        stop = serializer.save(**extra)
        trip.save(update_fields=["updated_at"])
        return Response(serialize_stops(stop, self._context(trip), many=False))

    @action(detail=True, methods=["post"])
    def reorder(self, request, pk=None):
        """{day, stop_ids}: put these stops on `day` in this order (stops may come from other days)."""
        trip = self.get_object()
        day, ids = request.data.get("day"), request.data.get("stop_ids")
        limit = trip.day_count or MAX_TRIP_DAYS
        if not isinstance(day, int) or isinstance(day, bool) or not 1 <= day <= limit:
            raise serializers.ValidationError({"day": f"Day must be between 1 and {limit}."})
        if (
            not isinstance(ids, list)
            or not all(isinstance(i, int) and not isinstance(i, bool) for i in ids)
            or len(set(ids)) != len(ids)
        ):
            raise serializers.ValidationError({"stop_ids": "Send a list of distinct stop ids."})
        with transaction.atomic():
            stops = {s.id: s for s in trip.stops.select_for_update().filter(id__in=ids)}
            if len(stops) != len(ids):
                raise serializers.ValidationError({"stop_ids": "Some stops are not part of this trip."})
            # stops already on that day but not listed keep their relative order after the listed ones
            ordered = [stops[i] for i in ids] + list(trip.stops.filter(day=day).exclude(id__in=ids).order_by("order", "id"))
            for index, stop in enumerate(ordered):
                stop.day, stop.order = day, index
            TripStop.objects.bulk_update(ordered, ["day", "order"])
            trip.save(update_fields=["updated_at"])
        return Response(TripDetailSerializer(self.get_queryset().get(pk=trip.pk), context=self.get_serializer_context()).data)
