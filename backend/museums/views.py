import datetime
import io
import math
import os
import uuid
from urllib.parse import urlparse

import django_filters
from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.files.base import ContentFile
from django.core.files.storage import default_storage
from django.db import transaction
from django.db.models import Avg, Case, Count, Exists, F, FloatField, IntegerField, OuterRef, Prefetch, Q, Subquery, Sum, Value, When
from django.db.models.functions import Coalesce
from django.utils import timezone
from django.utils.dateparse import parse_date
from rest_framework import mixins, permissions, serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied
from rest_framework.parsers import MultiPartParser
from rest_framework.response import Response
from rest_framework.views import APIView

from accounts.permissions import IsAdminRole, IsPanelUser

from .importer import import_museums
from .models import (
    REVIEW_PHOTO_MAX_MB, REVIEW_PHOTO_MAX_PER_REVIEW, Category, City, Museum, MuseumImage, PlaceClosure, PriceRule,
    Review, ReviewPhoto, ReviewVote, State, TicketType,
)
from .serializers import (
    AdminReviewSerializer,
    PlaceClosureSerializer,
    PriceRuleSerializer,
    PublicClosureSerializer,
    CategorySerializer,
    CitySerializer,
    MuseumDetailSerializer,
    MuseumImageSerializer,
    MuseumListSerializer,
    ReviewPhotoSerializer,
    ReviewSerializer,
    StateSerializer,
)


def crowd_level(booked, capacity):
    """quiet < 40% booked, moderate < 75%, busy < 100%, full."""
    share = booked / capacity if capacity else 1
    if share >= 1:
        return "full"
    if share >= 0.75:
        return "busy"
    if share >= 0.40:
        return "moderate"
    return "quiet"


def entered_by_slot(museum, visit_date):
    """People already through the gate per slot (from bookings' visitors_arrived)."""
    from bookings.models import Booking

    rows = (
        Booking.objects.filter(museum=museum, visit_date=visit_date, visitors_arrived__gt=0)
        .values("slot_id").annotate(n=Sum("visitors_arrived")).order_by()
    )
    return {r["slot_id"]: r["n"] for r in rows}


class ReadOnlyOrAdmin(permissions.BasePermission):
    def has_permission(self, request, view):
        if request.method in permissions.SAFE_METHODS:
            return True
        return IsAdminRole().has_permission(request, view)


class StateViewSet(viewsets.ModelViewSet):
    serializer_class = StateSerializer
    permission_classes = [ReadOnlyOrAdmin]
    pagination_class = None
    search_fields = ["name", "code"]

    def get_queryset(self):
        active = Q(cities__museums__is_active=True)
        place_type = self.request.query_params.get("type")
        if place_type:
            active &= Q(cities__museums__place_type=place_type)
        return State.objects.annotate(museum_count=Count("cities__museums", filter=active))


class CityViewSet(viewsets.ModelViewSet):
    queryset = City.objects.select_related("state")
    serializer_class = CitySerializer
    permission_classes = [ReadOnlyOrAdmin]
    pagination_class = None
    filterset_fields = ["state"]
    search_fields = ["name"]


class CategoryViewSet(viewsets.ModelViewSet):
    queryset = Category.objects.all()
    serializer_class = CategorySerializer
    permission_classes = [ReadOnlyOrAdmin]
    pagination_class = None


class MuseumFilter(django_filters.FilterSet):
    state = django_filters.NumberFilter(field_name="city__state")
    city = django_filters.NumberFilter(field_name="city")
    category = django_filters.NumberFilter(field_name="category")
    featured = django_filters.BooleanFilter(field_name="is_featured")
    active = django_filters.BooleanFilter(field_name="is_active")
    type = django_filters.MultipleChoiceFilter(field_name="place_type", choices=Museum.PlaceType.choices)
    verified = django_filters.BooleanFilter(field_name="info_verified")

    class Meta:
        model = Museum
        fields = ["state", "city", "category", "featured", "active", "type", "verified"]


PHOTO_FORMATS = {"JPEG": "jpg", "PNG": "png", "WEBP": "webp"}


def _local_media_path(url):
    """Storage path of an uploaded place photo, or None for external (e.g. Wikimedia) URLs."""
    path = urlparse(url or "").path
    if not path.startswith(settings.MEDIA_URL):
        return None
    relative = path[len(settings.MEDIA_URL):]
    return relative if relative.startswith("places/") and ".." not in relative else None


class MuseumViewSet(viewsets.ModelViewSet):
    lookup_field = "slug"
    permission_classes = [ReadOnlyOrAdmin]
    filterset_class = MuseumFilter
    search_fields = ["name", "tagline", "city__name", "city__state__name", "category__name"]
    ordering_fields = ["name", "established_year", "created_at", "avg_rating"]

    def get_queryset(self):
        qs = (
            Museum.objects.select_related("city__state", "category", "info_verified_by")
            .prefetch_related("ticket_types", "slots", "images")
            .annotate(
                # Per-place subqueries (index on museum+is_published) instead of joining every review:
                # only the places on the current page are computed, not all of them.
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
            # Bookable places first, then ones with a photo, then information-only listings; A-Z within each.
            # (Aggregates drop Meta.ordering; an explicit order keeps pagination stable.) ?ordering= overrides.
            .annotate(
                bookable=Exists(TicketType.objects.filter(museum=OuterRef("pk"), is_active=True)),
                has_photo=Case(When(image_url="", google_place_id="", then=Value(0)), default=Value(1),
                               output_field=IntegerField()),
            )
            .order_by("-bookable", "-has_photo", "name", "id")
        )
        user = self.request.user
        if not (user.is_authenticated and user.is_panel_user):
            qs = qs.filter(is_active=True)
        elif self.request.query_params.get("assigned") and not user.is_admin_role:
            qs = qs.filter(staff=user)  # ticket desks only offer the places this staff member works at
        return qs

    def get_serializer_class(self):
        return MuseumListSerializer if self.action == "list" else MuseumDetailSerializer

    @action(detail=False, methods=["get"], permission_classes=[permissions.AllowAny])
    def facets(self, request):
        """Result counts per filter option, each computed with all *other* active filters applied.

        Lets the explore page show "Archaeology (3)" and grey out options that would return nothing.
        """
        params = request.query_params
        visible = Museum.objects.filter(is_active=True)
        user = request.user
        if user.is_authenticated and user.is_panel_user:
            visible = Museum.objects.all()

        def filtered(without):
            data = params.copy()
            for key in without:
                data.pop(key, None)
            qs = MuseumFilter(data, queryset=visible).qs
            search = data.get("search", "").strip()
            if search:
                for term in search.split():
                    qs = qs.filter(
                        Q(name__icontains=term) | Q(tagline__icontains=term) | Q(city__name__icontains=term)
                        | Q(city__state__name__icontains=term) | Q(category__name__icontains=term)
                    )
            return qs

        def counts(qs, field):
            return {str(r[field]): r["n"] for r in qs.order_by().values(field).annotate(n=Count("id")) if r[field] is not None}

        return Response({
            "total": filtered([]).count(),
            "type": counts(filtered(["type"]), "place_type"),
            "state": counts(filtered(["state", "city"]), "city__state"),
            "city": counts(filtered(["city"]), "city"),
            "category": counts(filtered(["category"]), "category"),
        })

    @action(detail=True, methods=["get"], permission_classes=[permissions.AllowAny])
    def availability(self, request, slug=None):
        """Remaining capacity for each slot on ?date=YYYY-MM-DD."""
        from bookings.services import booked_visitors_by_slot, group_cap, group_seats_by_slot, prices_for

        museum = self.get_object()
        visit_date = parse_date(request.query_params.get("date", "") or "")
        if not visit_date:
            return Response({"detail": "Pass ?date=YYYY-MM-DD"}, status=status.HTTP_400_BAD_REQUEST)

        today = timezone.localdate()
        last_day = today + datetime.timedelta(days=settings.BOOKING_WINDOW_DAYS)
        bookable = today <= visit_date <= last_day
        closure = museum.closure_on(visit_date)
        closed = museum.is_closed_on(visit_date) or closure["closed"]
        booked = booked_visitors_by_slot(museum, visit_date)
        entered = entered_by_slot(museum, visit_date) if visit_date == today else None
        group_booked = group_seats_by_slot(museum, visit_date) if museum.allow_groups else {}
        now = timezone.localtime().time()
        # Ticket counter staff can sell into a slot that is running; online visitors cannot.
        user = request.user
        counter = bool(request.query_params.get("counter")) and user.is_authenticated and user.is_panel_user

        slots = []
        for slot in museum.slots.filter(is_active=True):
            taken = booked.get(slot.id, 0)
            cutoff = slot.end_time if counter else slot.start_time
            started = visit_date == today and cutoff <= now
            available = max(slot.capacity - taken, 0)
            slot_closed = closure["slots"].get(slot.id)
            extra = {"entered_so_far": entered.get(slot.id, 0)} if entered is not None else {}
            slots.append({
                "id": slot.id,
                "start_time": slot.start_time,
                "end_time": slot.end_time,
                "capacity": slot.capacity,
                "booked": taken,
                "available": available,
                # How many more people may come in groups (groups are capped at a share of the slot).
                "group_available": max(min(group_cap(slot) - group_booked.get(slot.id, 0), available), 0)
                if museum.allow_groups else 0,
                "bookable": bookable and not closed and not slot_closed and not started and taken < slot.capacity,
                "closed_reason": slot_closed,  # partial closure of this slot (None when open)
                "crowd": crowd_level(taken, slot.capacity),
                **extra,
            })
        return Response({
            "date": visit_date,
            "closed": closed,
            # Why the day is closed: the calendar reason, or None for the weekly closed day / an open day.
            "closure_reason": closure["reason"] if closure["closed"] else None,
            "bookable": bookable and not closed,
            "slots": slots,
            "prices": prices_for(museum, visit_date),
        })

    @action(detail=True, methods=["get"], permission_classes=[permissions.AllowAny])
    def prices(self, request, slug=None):
        """Per-ticket prices on ?date=YYYY-MM-DD after seasonal / peak price rules."""
        from bookings.services import prices_for

        museum = self.get_object()
        visit_date = parse_date(request.query_params.get("date", "") or "") or timezone.localdate()
        return Response({"date": visit_date, "prices": prices_for(museum, visit_date)})

    @action(detail=True, methods=["get"], permission_classes=[permissions.AllowAny],
            url_path=r"google-photo/(?P<index>\d+)")
    def google_photo(self, request, slug=None, index=0):
        """Redirect to a Google Maps photo of a place without its own photo (see museums/google_places.py)."""
        from django.http import HttpResponseRedirect

        from . import google_places

        place_id = Museum.objects.filter(slug=slug, is_active=True).values_list("google_place_id", flat=True).first()
        uri = google_places.photo_uri(place_id, int(index)) if place_id and google_places.enabled() else None
        if not uri:
            return Response(status=status.HTTP_404_NOT_FOUND)
        response = HttpResponseRedirect(uri)
        response["Cache-Control"] = "public, max-age=3600"
        return response

    @action(detail=True, methods=["get"], permission_classes=[permissions.AllowAny])
    def closures(self, request, slug=None):
        """Closures (this place's and all-place ones) between ?from and ?to (default: the booking window)."""
        museum = self.get_object()
        start = parse_date(request.query_params.get("from", "") or "") or timezone.localdate()
        end = parse_date(request.query_params.get("to", "") or "") or (
            start + datetime.timedelta(days=settings.BOOKING_WINDOW_DAYS)
        )
        if end < start:
            return Response({"detail": "The end date must be on or after the start date."},
                            status=status.HTTP_400_BAD_REQUEST)
        end = min(end, start + datetime.timedelta(days=366))
        qs = PlaceClosure.covering(museum, start, end).prefetch_related("slots")[:100]
        return Response(PublicClosureSerializer(qs, many=True).data)

    @action(detail=False, methods=["post"], permission_classes=[IsAdminRole], url_path="import",
            parser_classes=[MultiPartParser])
    def import_csv(self, request):
        """Bulk add/update museums from a CSV upload (same format as museums/data/india_museums.csv)."""
        upload = request.FILES.get("file")
        if not upload:
            raise serializers.ValidationError({"file": "Upload a .csv file."})
        try:
            text = upload.read().decode("utf-8-sig")
        except UnicodeDecodeError:
            raise serializers.ValidationError({"file": "Save the file as CSV UTF-8."})
        update = request.data.get("update") in ("1", "true", "True")
        return Response(import_museums(io.StringIO(text), update=update))

    @action(detail=True, methods=["post"], permission_classes=[IsAdminRole], url_path="photos",
            parser_classes=[MultiPartParser])
    def upload_photo(self, request, slug=None):
        """Upload our own photo: added to the gallery, or made the main photo with make_main=1."""
        from PIL import Image, UnidentifiedImageError

        museum = self.get_object()
        upload = request.FILES.get("file")
        if not upload:
            raise serializers.ValidationError({"file": "Choose a JPG, PNG or WebP image."})
        if upload.size > settings.MAX_UPLOAD_MB * 1024 * 1024:
            raise serializers.ValidationError({"file": f"The image is larger than {settings.MAX_UPLOAD_MB} MB."})
        data = upload.read()
        try:
            with Image.open(io.BytesIO(data)) as img:
                fmt = img.format
                img.verify()
        except (UnidentifiedImageError, OSError, SyntaxError, ValueError):
            raise serializers.ValidationError({"file": "This file is not a readable image."})
        if fmt not in PHOTO_FORMATS:
            raise serializers.ValidationError({"file": "Only JPG, PNG and WebP images are allowed."})

        caption = (request.data.get("caption") or "").strip()[:200]
        credit = (request.data.get("credit") or "").strip()[:300]
        make_main = str(request.data.get("make_main", "")).lower() in ("1", "true", "yes", "on")

        name = f"places/{museum.slug}/{uuid.uuid4().hex[:12]}.{PHOTO_FORMATS[fmt]}"
        saved = default_storage.save(name, ContentFile(data))
        url = request.build_absolute_uri(settings.MEDIA_URL + saved.replace(os.sep, "/"))

        if make_main:
            museum.image_url = url
            museum.image_credit = credit
            museum.image_source_url = ""
            museum.save(update_fields=["image_url", "image_credit", "image_source_url", "updated_at"])
            return Response({"main": True, "image_url": url, "image_credit": credit}, status=status.HTTP_201_CREATED)

        last = museum.images.order_by("-sort_order").first()
        image = MuseumImage.objects.create(
            museum=museum, url=url, caption=caption, credit=credit,
            sort_order=(last.sort_order + 1) if last else 0,
        )
        return Response(MuseumImageSerializer(image).data, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=["delete"], permission_classes=[IsAdminRole], url_path=r"photos/(?P<photo_id>[0-9]+)")
    def delete_photo(self, request, slug=None, photo_id=None):
        """Remove a gallery photo (and its file, if it was uploaded here rather than linked)."""
        museum = self.get_object()
        image = museum.images.filter(pk=photo_id).first()
        if not image:
            return Response({"detail": "Photo not found."}, status=status.HTTP_404_NOT_FOUND)
        path = _local_media_path(image.url)
        in_use = museum.image_url == image.url or museum.images.filter(url=image.url).exclude(pk=image.pk).exists()
        image.delete()
        if path and not in_use and default_storage.exists(path):
            default_storage.delete(path)
        return Response(status=status.HTTP_204_NO_CONTENT)

    @action(detail=True, methods=["get", "post", "delete"], permission_classes=[permissions.IsAuthenticatedOrReadOnly])
    def reviews(self, request, slug=None):
        """GET: summary + published reviews (+ whether you may review). POST: write/update yours. DELETE: remove yours."""
        museum = self.get_object()
        user = request.user

        if request.method == "POST":
            if not Review.user_can_review(user, museum):
                raise serializers.ValidationError("You can review this museum after your visit.")
            serializer = ReviewSerializer(data=request.data)
            serializer.is_valid(raise_exception=True)
            review, _ = museum.reviews.update_or_create(user=user, defaults=serializer.validated_data)
            return Response(ReviewSerializer(review, context={"request": request, "own_review": True}).data,
                            status=status.HTTP_201_CREATED)

        if request.method == "DELETE":
            museum.reviews.filter(user=user).delete()
            return Response(status=status.HTTP_204_NO_CONTENT)

        published = museum.reviews.filter(is_published=True)
        sort = request.query_params.get("sort")
        # Newest first by default; "helpful" = most helpful votes first (newest breaks ties), on its own index.
        if sort == "oldest":
            ordering = ("created_at", "id")
        elif sort == "helpful":
            ordering = ("-helpful_count", "-created_at", "-id")
        else:
            ordering = ("-created_at", "-id")
        # Other visitors' reviews come a page at a time (?offset=&limit=, max 20) so busy places stay light;
        # ?stars=4 shows the 4-star bar (4 and 4.5), matching the breakdown buckets.
        def int_param(name, default, low, high):
            try:
                return min(max(int(request.query_params.get(name, default)), low), high)
            except (TypeError, ValueError):
                return default

        offset, limit = int_param("offset", 0, 0, 10**9), int_param("limit", 5, 1, 20)
        listed = published.exclude(user=user) if user.is_authenticated else published
        stars = int_param("stars", 0, 0, 5)
        if stars:
            listed = listed.filter(rating__gte=0 if stars == 1 else stars, rating__lt=stars + 1)
        listed_total = listed.count()
        stats = published.aggregate(avg=Avg("rating"), count=Count("id"))
        breakdown = {str(n): 0 for n in range(5, 0, -1)}
        for row in published.values("rating").annotate(n=Count("id")).order_by():
            # Half stars count toward the star below (4.5 -> the 4-star bar; 0.5 -> 1 star), like their label.
            bucket = str(max(1, math.floor(row["rating"])))
            breakdown[bucket] = breakdown.get(bucket, 0) + row["n"]
        mine = museum.reviews.filter(user=user).prefetch_related("photos").first() if user.is_authenticated else None
        approved = Prefetch("photos", queryset=ReviewPhoto.objects.filter(status=ReviewPhoto.Status.APPROVED))
        page = list(listed.order_by(*ordering).select_related("user").prefetch_related(approved)[offset:offset + limit])
        voted_ids = set(
            ReviewVote.objects.filter(user=user, review_id__in=[r.id for r in page]).values_list("review_id", flat=True)
        ) if user.is_authenticated and page else set()
        ctx = {"request": request}
        visitor_photos = (
            ReviewPhoto.objects.filter(review__museum=museum, review__is_published=True,
                                       status=ReviewPhoto.Status.APPROVED)
            .select_related("review__user").order_by("-created_at")[:24]
        )
        return Response({
            "average": round(float(stats["avg"]), 1) if stats["avg"] else None,
            "count": stats["count"],
            "breakdown": breakdown,
            "can_review": Review.user_can_review(user, museum),
            "my_review": ReviewSerializer(mine, context={**ctx, "own_review": True}).data if mine else None,
            "results": ReviewSerializer(page, many=True, context={**ctx, "voted_ids": voted_ids}).data,
            "results_total": listed_total,
            "next_offset": offset + limit if offset + limit < listed_total else None,
            # Approved photos from published reviews, newest first (the "Visitor photos" strip).
            "visitor_photos": [
                {**ReviewPhotoSerializer(p, context=ctx).data, "review_id": p.review_id,
                 "user_name": ReviewSerializer().get_user_name(p.review), "rating": float(p.review.rating)}
                for p in visitor_photos
            ],
            "photo_limits": {"max_per_review": REVIEW_PHOTO_MAX_PER_REVIEW, "max_mb": REVIEW_PHOTO_MAX_MB},
        })

    @action(detail=True, methods=["post", "delete"], url_path=r"reviews/(?P<review_id>[0-9]+)/helpful",
            permission_classes=[permissions.IsAuthenticated])
    def review_helpful(self, request, slug=None, review_id=None):
        """POST: mark a published review helpful; DELETE: take the vote back. Both are idempotent.

        Not on your own review. Review.helpful_count moves with F() in the same transaction as the vote row,
        so concurrent votes never lose an update (the unique (review, user) pair stops double votes).
        """
        museum = self.get_object()
        review = museum.reviews.filter(pk=review_id, is_published=True).only("id", "user_id").first()
        if not review:
            return Response({"detail": "Review not found."}, status=status.HTTP_404_NOT_FOUND)
        user = request.user
        if review.user_id == user.id:
            raise PermissionDenied("You can't vote on your own review.")
        with transaction.atomic():
            if request.method == "POST":
                _, created = ReviewVote.objects.get_or_create(review_id=review.id, user=user)
                if created:
                    Review.objects.filter(pk=review.id).update(helpful_count=F("helpful_count") + 1)
            else:
                # Each deleted vote lowers the count once, in the ReviewVote post_delete signal.
                ReviewVote.objects.filter(review_id=review.id, user=user).delete()
        count = Review.objects.filter(pk=review.id).values_list("helpful_count", flat=True).first() or 0
        return Response({"id": review.id, "helpful_count": count, "voted_by_me": request.method == "POST"})

    @action(detail=True, methods=["post"], url_path="reviews/photos", parser_classes=[MultiPartParser],
            permission_classes=[permissions.IsAuthenticated])
    def review_photos(self, request, slug=None):
        """Add photos (field "file", repeatable) to your own review. They stay hidden until approved."""
        from PIL import Image, UnidentifiedImageError

        museum = self.get_object()
        review = museum.reviews.filter(user=request.user).first()
        if not review:
            raise serializers.ValidationError("Write your review first, then add photos.")
        uploads = request.FILES.getlist("file")
        if not uploads:
            raise serializers.ValidationError({"file": "Choose a JPG, PNG or WebP image."})
        existing = review.photos.exclude(status=ReviewPhoto.Status.REJECTED).count()
        if existing + len(uploads) > REVIEW_PHOTO_MAX_PER_REVIEW:
            raise serializers.ValidationError(
                {"file": f"A review can have up to {REVIEW_PHOTO_MAX_PER_REVIEW} photos."})
        checked = []
        for upload in uploads:
            if upload.size > REVIEW_PHOTO_MAX_MB * 1024 * 1024:
                raise serializers.ValidationError({"file": f"Each photo must be {REVIEW_PHOTO_MAX_MB} MB or smaller."})
            data = upload.read()
            try:
                with Image.open(io.BytesIO(data)) as img:
                    fmt = img.format
                    img.verify()
            except (UnidentifiedImageError, OSError, SyntaxError, ValueError):
                raise serializers.ValidationError({"file": "This file is not a readable image."})
            if fmt not in PHOTO_FORMATS:
                raise serializers.ValidationError({"file": "Only JPG, PNG and WebP images are allowed."})
            checked.append((data, PHOTO_FORMATS[fmt]))
        created = []
        for data, ext in checked:
            photo = ReviewPhoto(review=review)
            photo.image.save(f"{museum.slug[:60]}-{uuid.uuid4().hex[:12]}.{ext}", ContentFile(data), save=True)
            created.append(photo)
        return Response(ReviewPhotoSerializer(created, many=True, context={"request": request}).data,
                        status=status.HTTP_201_CREATED)

    @action(detail=True, methods=["delete"], url_path=r"reviews/photos/(?P<photo_id>[0-9]+)",
            permission_classes=[permissions.IsAuthenticated])
    def delete_review_photo(self, request, slug=None, photo_id=None):
        """Remove one of your own review photos."""
        museum = self.get_object()
        photo = ReviewPhoto.objects.filter(pk=photo_id, review__museum=museum, review__user=request.user).first()
        if not photo:
            return Response({"detail": "Photo not found."}, status=status.HTTP_404_NOT_FOUND)
        photo.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


class AdminReviewFilter(django_filters.FilterSet):
    """?rating=4 matches the 4-star bar: 4 and 4.5 (half stars count toward the star below; 0.5 is in 1 star)."""

    rating = django_filters.NumberFilter(method="filter_rating")
    has_pending_photos = django_filters.BooleanFilter(method="filter_pending_photos")

    class Meta:
        model = Review
        fields = ["rating", "is_published", "museum__slug"]

    def filter_pending_photos(self, queryset, name, value):
        pending = ReviewPhoto.objects.filter(review=OuterRef("pk"), status=ReviewPhoto.Status.PENDING)
        return queryset.filter(Exists(pending)) if value else queryset.exclude(Exists(pending))

    def filter_rating(self, queryset, name, value):
        low = 0 if value <= 1 else value
        return queryset.filter(rating__gte=low, rating__lt=value + 1)


class AdminReviewViewSet(
    mixins.ListModelMixin, mixins.UpdateModelMixin, mixins.DestroyModelMixin, viewsets.GenericViewSet
):
    """Moderation: list every review, hide/unhide, delete."""

    queryset = Review.objects.select_related("museum", "user").prefetch_related("photos")
    serializer_class = AdminReviewSerializer
    permission_classes = [IsAdminRole]
    filterset_class = AdminReviewFilter
    search_fields = ["title", "comment", "museum__name", "user__email"]

    @action(detail=True, methods=["patch"], url_path=r"photos/(?P<photo_id>[0-9]+)")
    def moderate_photo(self, request, pk=None, photo_id=None):
        """PATCH {"status": "approved" | "rejected" | "pending"} for one photo of this review."""
        review = self.get_object()
        photo = review.photos.filter(pk=photo_id).first()
        if not photo:
            return Response({"detail": "Photo not found."}, status=status.HTTP_404_NOT_FOUND)
        new_status = request.data.get("status")
        if new_status not in ReviewPhoto.Status.values:
            raise serializers.ValidationError({"status": "Use approved, rejected or pending."})
        photo.status = new_status
        photo.save(update_fields=["status"])
        return Response(ReviewPhotoSerializer(photo, context={"request": request}).data)


class StaffMuseumsView(APIView):
    """Admin: which places a staff member is assigned to. PUT {"museums": [slug, ...]} replaces the list."""

    permission_classes = [IsAdminRole]

    def _payload(self, user):
        museums = user.assigned_museums.select_related("city__state").order_by("name")
        return {
            "user": user.id,
            "email": user.email,
            "museums": [
                {"slug": m.slug, "name": m.name, "city_name": m.city.name, "state_name": m.city.state.name}
                for m in museums
            ],
        }

    def get(self, request, user_id):
        user = get_user_model().objects.filter(pk=user_id).first()
        if not user:
            return Response({"detail": "User not found."}, status=status.HTTP_404_NOT_FOUND)
        return Response(self._payload(user))

    def put(self, request, user_id):
        user = get_user_model().objects.filter(pk=user_id).first()
        if not user:
            return Response({"detail": "User not found."}, status=status.HTTP_404_NOT_FOUND)
        if user.is_admin_role or user.role != user.Role.STAFF:
            raise serializers.ValidationError("Only staff users are assigned to places; administrators see every place.")
        slugs = request.data.get("museums")
        if not isinstance(slugs, list) or not all(isinstance(s, str) for s in slugs):
            raise serializers.ValidationError({"museums": "Send a list of place slugs."})
        slugs = list(dict.fromkeys(s.strip() for s in slugs if s.strip()))
        museums = list(Museum.objects.filter(slug__in=slugs))
        missing = sorted(set(slugs) - {m.slug for m in museums})
        if missing:
            raise serializers.ValidationError({"museums": f"Unknown place(s): {', '.join(missing)}"})
        user.assigned_museums.set(museums)
        return Response(self._payload(user))


class PanelReadAdminWrite(permissions.BasePermission):
    """Staff may read (their places); only administrators may change."""

    def has_permission(self, request, view):
        if request.method in permissions.SAFE_METHODS:
            return IsPanelUser().has_permission(request, view)
        return IsAdminRole().has_permission(request, view)


class AdminClosureViewSet(viewsets.ModelViewSet):
    """Closures calendar. ?museum=<slug> (also returns all-place closures), ?upcoming=1, ?scope=global."""

    serializer_class = PlaceClosureSerializer
    permission_classes = [PanelReadAdminWrite]
    pagination_class = None

    def get_queryset(self):
        qs = PlaceClosure.objects.select_related("museum", "created_by").prefetch_related("slots")
        user = self.request.user
        if not user.is_admin_role:
            qs = qs.filter(Q(museum__in=Museum.for_panel_user(user)) | Q(museum__isnull=True))
        params = self.request.query_params
        if params.get("museum"):
            qs = qs.filter(Q(museum__slug=params["museum"]) | Q(museum__isnull=True))
        if params.get("scope") == "global":
            qs = qs.filter(museum__isnull=True)
        if params.get("upcoming"):
            qs = qs.filter(end_date__gte=timezone.localdate())
        return qs.order_by("start_date", "id")

    def perform_create(self, serializer):
        serializer.save(created_by=self.request.user)


class AdminPriceRuleViewSet(viewsets.ModelViewSet):
    """Seasonal / peak price rules. ?museum=<slug>."""

    serializer_class = PriceRuleSerializer
    permission_classes = [PanelReadAdminWrite]
    pagination_class = None

    def get_queryset(self):
        qs = PriceRule.objects.select_related("museum", "ticket_type").filter(
            museum__in=Museum.for_panel_user(self.request.user)
        )
        if self.request.query_params.get("museum"):
            qs = qs.filter(museum__slug=self.request.query_params["museum"])
        return qs


class PublicSiteSettingsView(APIView):
    """What visitors need to know: which kinds of group visit are open site-wide."""

    permission_classes = [permissions.AllowAny]

    def get(self, request):
        from .models import SiteSettings

        site = SiteSettings.load()
        return Response({
            "individual_bookings_enabled": site.individual_bookings_enabled,
            "group_bookings_enabled": site.group_bookings_enabled,
            "group_requests_enabled": site.group_requests_enabled,
            "school_trips_enabled": site.school_trips_enabled,
            "events_enabled": site.events_enabled,
            "passes_enabled": site.passes_enabled,
            "paused_message": site.paused_message,
            "footer_brand": site.footer_brand,
            "footer_tagline": site.footer_tagline,
            "footer_copyright": site.footer_copyright,
        })


class AdminSiteSettingsView(APIView):
    """Admin -> Settings: GET the switches, PATCH to change them (recorded in the audit log)."""

    permission_classes = [IsAdminRole]

    def get(self, request):
        from .models import SiteSettings
        from .serializers import SiteSettingsSerializer

        return Response(SiteSettingsSerializer(SiteSettings.load()).data)

    def patch(self, request):
        from audit.services import record

        from .models import SiteSettings
        from .serializers import SiteSettingsSerializer

        site, _ = SiteSettings.objects.get_or_create(pk=1)
        serializer = SiteSettingsSerializer(site, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        changes = {k: v for k, v in serializer.validated_data.items() if getattr(site, k) != v}
        site = serializer.save(updated_by=request.user)
        if changes:
            record(request, "site_settings.update", user=request.user, object_repr="Site settings",
                   changes={k: str(v) for k, v in changes.items()})
        return Response(SiteSettingsSerializer(site).data)
