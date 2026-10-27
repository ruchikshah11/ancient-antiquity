from decimal import Decimal

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.db.models.signals import post_delete
from django.dispatch import receiver
from django.utils.text import slugify


class State(models.Model):
    """Indian state or union territory."""

    name = models.CharField(max_length=80, unique=True)
    code = models.CharField(max_length=4, unique=True)
    is_union_territory = models.BooleanField(default=False)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name


class City(models.Model):
    name = models.CharField(max_length=80)
    state = models.ForeignKey(State, on_delete=models.PROTECT, related_name="cities")

    class Meta:
        ordering = ["name"]
        unique_together = ("name", "state")
        verbose_name_plural = "cities"

    def __str__(self):
        return f"{self.name}, {self.state.name}"


class Category(models.Model):
    name = models.CharField(max_length=60, unique=True)
    slug = models.SlugField(max_length=70, unique=True, blank=True)

    class Meta:
        ordering = ["name"]
        verbose_name_plural = "categories"

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = slugify(self.name)
        super().save(*args, **kwargs)

    def __str__(self):
        return self.name


class Museum(models.Model):
    class Weekday(models.IntegerChoices):
        MONDAY = 0, "Monday"
        TUESDAY = 1, "Tuesday"
        WEDNESDAY = 2, "Wednesday"
        THURSDAY = 3, "Thursday"
        FRIDAY = 4, "Friday"
        SATURDAY = 5, "Saturday"
        SUNDAY = 6, "Sunday"

    class PlaceType(models.TextChoices):
        MUSEUM = "museum", "Museum"
        FORT = "fort", "Fort"
        PALACE = "palace", "Palace"
        MONUMENT = "monument", "Monument"

    class VirtualTourKind(models.TextChoices):
        TOUR_360 = "360", "360° tour"
        VIDEO = "video", "Video"
        STREET_VIEW = "google_street_view", "Google Street View"
        OTHER = "other", "Other"

    name = models.CharField(max_length=150)
    slug = models.SlugField(max_length=170, unique=True, blank=True)
    place_type = models.CharField(max_length=10, choices=PlaceType.choices, default=PlaceType.MUSEUM, db_index=True)
    city = models.ForeignKey(City, on_delete=models.PROTECT, related_name="museums")
    category = models.ForeignKey(
        Category, on_delete=models.SET_NULL, null=True, blank=True, related_name="museums"
    )
    tagline = models.CharField(max_length=200, blank=True)
    description = models.TextField()
    highlights = models.TextField(blank=True, help_text="One highlight per line")
    address = models.CharField(max_length=255)
    latitude = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    longitude = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    image_url = models.URLField(max_length=500, blank=True)
    image_credit = models.CharField(max_length=300, blank=True, help_text="Photographer / licence for image_url")
    image_source_url = models.URLField(max_length=500, blank=True)
    # Google Maps place (Places API) used for photos when the place has none of its own; see museums/google_places.py
    google_place_id = models.CharField(max_length=300, blank=True)
    google_place_name = models.CharField(max_length=200, blank=True, help_text="Name of the matched Google place")
    source_url = models.URLField(max_length=500, blank=True, help_text="Where the description was adapted from")
    established_year = models.PositiveIntegerField(null=True, blank=True)
    managed_by = models.CharField(max_length=150, blank=True)
    contact_phone = models.CharField(max_length=20, blank=True)
    contact_email = models.EmailField(blank=True)
    opening_time = models.TimeField()
    closing_time = models.TimeField()
    closed_weekday = models.IntegerField(choices=Weekday.choices, null=True, blank=True)
    is_featured = models.BooleanField(default=False)
    is_active = models.BooleanField(default=True)
    allow_groups = models.BooleanField(default=True, help_text="Accept group bookings (21-60 people)")
    allow_individual = models.BooleanField(
        default=True, help_text="Accept individual online tickets (switch off for a groups-only place)",
    )
    group_discount_percent = models.PositiveSmallIntegerField(
        default=10, validators=[MaxValueValidator(90)], help_text="Discount for tour/company/other groups"
    )
    school_discount_percent = models.PositiveSmallIntegerField(
        default=25, validators=[MaxValueValidator(100)], help_text="Discount for school and college groups"
    )
    staff = models.ManyToManyField(
        settings.AUTH_USER_MODEL, blank=True, related_name="assigned_museums",
        help_text="Staff users who may sell, scan and report for this place",
    )
    facilities = models.JSONField(
        default=dict, blank=True,
        help_text="Visitor information: accessibility, amenities, photography rules, getting there (see FACILITY_FLAGS)",
    )
    virtual_tour_url = models.URLField(max_length=500, blank=True, help_text="360 tour, video walk-through or Street View")
    virtual_tour_kind = models.CharField(max_length=20, choices=VirtualTourKind.choices, blank=True)
    info_verified = models.BooleanField(default=False, help_text="Timings and prices confirmed with the place")
    info_verified_at = models.DateTimeField(null=True, blank=True)
    info_verified_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["name"]

    def save(self, *args, **kwargs):
        if not self.slug:
            base = slugify(f"{self.name}-{self.city.name}")[:160]
            slug, n = base, 2
            while Museum.objects.filter(slug=slug).exclude(pk=self.pk).exists():
                slug, n = f"{base}-{n}", n + 1
            self.slug = slug
        super().save(*args, **kwargs)

    @classmethod
    def for_panel_user(cls, user):
        """Places a panel user may work on: admins everything, staff only the ones assigned to them."""
        if user.is_admin_role:
            return cls.objects.all()
        return cls.objects.filter(staff=user)

    def is_closed_on(self, day):
        return self.closed_weekday is not None and day.weekday() == self.closed_weekday

    def closure_on(self, day):
        """Calendar closures on `day` (on top of the weekly closed day).

        Returns {"closed": bool, "reason": str, "slots": {slot_id: reason}}: a whole-day closure (for this
        place or for all places) closes the day; partial closures only close the listed slots.
        """
        info = {"closed": False, "reason": "", "slots": {}}
        for closure in PlaceClosure.covering(self, day, day).prefetch_related("slots"):
            if closure.all_day:
                if not info["closed"]:
                    info["closed"], info["reason"] = True, closure.reason
            else:
                for slot in closure.slots.all():
                    info["slots"].setdefault(slot.id, closure.reason)
        return info

    def __str__(self):
        return self.name


class MuseumImage(models.Model):
    """Gallery photo. Credit and source are required for Wikimedia Commons images."""

    museum = models.ForeignKey(Museum, on_delete=models.CASCADE, related_name="images")
    url = models.URLField(max_length=500)
    caption = models.CharField(max_length=200, blank=True)
    credit = models.CharField(max_length=300, blank=True)
    source_url = models.URLField(max_length=500, blank=True)
    sort_order = models.PositiveSmallIntegerField(default=0)

    class Meta:
        ordering = ["sort_order", "id"]

    def __str__(self):
        return f"{self.museum.name} image {self.sort_order}"


class TicketType(models.Model):
    """A visitor category with its own price, e.g. Indian adult, foreign national."""

    museum = models.ForeignKey(Museum, on_delete=models.CASCADE, related_name="ticket_types")
    name = models.CharField(max_length=60)
    description = models.CharField(max_length=150, blank=True)
    price = models.DecimalField(max_digits=8, decimal_places=2, validators=[MinValueValidator(0)])
    sort_order = models.PositiveSmallIntegerField(default=0)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["sort_order", "id"]

    def __str__(self):
        return f"{self.museum.name} - {self.name}"


class TimeSlot(models.Model):
    """Recurring daily entry slot. Availability is calculated per visit date."""

    museum = models.ForeignKey(Museum, on_delete=models.CASCADE, related_name="slots")
    start_time = models.TimeField()
    end_time = models.TimeField()
    capacity = models.PositiveIntegerField(validators=[MinValueValidator(1)])
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["start_time"]

    def __str__(self):
        return f"{self.museum.name} {self.start_time:%H:%M}-{self.end_time:%H:%M}"


def validate_half_step(value):
    """Ratings go in half stars: 0.5, 1, 1.5 … 5."""
    if (Decimal(value) * 2) % 1:
        raise ValidationError("Use whole or half stars (for example 4 or 4.5).")


class Review(models.Model):
    museum = models.ForeignKey(Museum, on_delete=models.CASCADE, related_name="reviews")
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="reviews")
    # 0.5 to 5 in half-star steps (4.5, 3.5 …).
    rating = models.DecimalField(
        max_digits=2, decimal_places=1,
        validators=[MinValueValidator(Decimal("0.5")), MaxValueValidator(Decimal("5")), validate_half_step],
    )
    title = models.CharField(max_length=120, blank=True)
    comment = models.TextField(blank=True)
    is_published = models.BooleanField(default=True, help_text="Untick to hide from the public site")
    # Denormalised count of ReviewVote rows, kept in step with F() updates (see MuseumViewSet.review_helpful).
    helpful_count = models.PositiveIntegerField(default=0, help_text="Visitors who found this review helpful")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]
        unique_together = ("museum", "user")
        indexes = [
            models.Index(fields=["museum", "is_published", "-created_at"], name="review_place_published_idx"),
            # ?sort=helpful on a place's reviews.
            models.Index(fields=["museum", "is_published", "-helpful_count", "-created_at"], name="review_place_helpful_idx"),
        ]

    @staticmethod
    def user_can_review(user, museum):
        """Only real visitors: checked in at the gate, or a paid ticket whose visit date has passed."""
        if not user.is_authenticated:
            return False
        from django.utils import timezone

        from bookings.models import Booking

        return Booking.objects.filter(user=user, museum=museum).filter(
            models.Q(status=Booking.Status.CHECKED_IN)
            | models.Q(status=Booking.Status.CONFIRMED, visit_date__lt=timezone.localdate())
        ).exists()

    def __str__(self):
        return f"{self.museum.name} - {self.rating:g}*"


class ReviewVote(models.Model):
    """One visitor found one review helpful. Review.helpful_count mirrors the number of these rows."""

    review = models.ForeignKey(Review, on_delete=models.CASCADE, related_name="votes")
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="review_votes")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ("review", "user")

    def __str__(self):
        return f"{self.user_id} found review {self.review_id} helpful"


@receiver(post_delete, sender=ReviewVote)
def _vote_deleted(sender, instance, **kwargs):
    """A vote removed by a cascade (e.g. the voter's account deleted) still lowers the count.

    The helpful API deletes votes through this same signal, so there is exactly one place that decrements.
    """
    Review.objects.filter(pk=instance.review_id, helpful_count__gt=0).update(helpful_count=models.F("helpful_count") - 1)


REVIEW_PHOTO_MAX_MB = 5
REVIEW_PHOTO_MAX_PER_REVIEW = 4


class ReviewPhoto(models.Model):
    """A visitor's photo attached to their review. Shown publicly only after a moderator approves it."""

    class Status(models.TextChoices):
        PENDING = "pending", "Waiting for approval"
        APPROVED = "approved", "Approved"
        REJECTED = "rejected", "Rejected"

    review = models.ForeignKey(Review, on_delete=models.CASCADE, related_name="photos")
    image = models.ImageField(upload_to="reviews/%Y/%m/")
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.PENDING, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at", "id"]

    def __str__(self):
        return f"Photo {self.pk} for review {self.review_id} ({self.status})"


@receiver(post_delete, sender=ReviewPhoto)
def _delete_review_photo_file(sender, instance, **kwargs):
    """Remove the file too (also when the review or place is deleted)."""
    if instance.image:
        instance.image.delete(save=False)


# Keys of Museum.facilities. Flags are switches; the rest are short texts (photography is a choice).
FACILITY_FLAGS = (
    "wheelchair", "lift", "toilets", "accessible_toilet", "drinking_water", "cloakroom", "parking",
    "cafeteria", "wifi", "guide_available", "audio_guide", "baby_care",
)
FACILITY_TEXTS = (
    "camera_fee_note", "nearest_metro", "nearest_station", "best_time_to_visit", "dress_code", "notes",
)
PHOTOGRAPHY_CHOICES = ("allowed", "no_flash", "not_allowed", "paid")


class PlaceClosure(models.Model):
    """A date range when a place (or every place, museum=None) is closed, wholly or for some slots."""

    museum = models.ForeignKey(
        Museum, on_delete=models.CASCADE, null=True, blank=True, related_name="closures",
        help_text="Leave empty for a closure that applies to all places (e.g. a national holiday)",
    )
    start_date = models.DateField(db_index=True)
    end_date = models.DateField(db_index=True)
    reason = models.CharField(max_length=200)
    all_day = models.BooleanField(default=True, help_text="Untick and pick slots for a partial closure")
    slots = models.ManyToManyField(TimeSlot, blank=True, related_name="closures")
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["start_date", "id"]

    @classmethod
    def covering(cls, museum, start, end):
        """Closures of `museum` (and all-place closures) overlapping start..end."""
        return cls.objects.filter(
            models.Q(museum=museum) | models.Q(museum__isnull=True), start_date__lte=end, end_date__gte=start
        )

    def __str__(self):
        where = self.museum.name if self.museum_id else "All places"
        return f"{where}: {self.start_date} to {self.end_date} {self.reason}"


class PriceRule(models.Model):
    """Seasonal / peak price change. The highest-priority active rule matching a ticket and date wins."""

    class Adjustment(models.TextChoices):
        PERCENT = "percent", "Percent change"
        FIXED_PRICE = "fixed_price", "Fixed price"

    museum = models.ForeignKey(Museum, on_delete=models.CASCADE, related_name="price_rules")
    name = models.CharField(max_length=100)
    start_date = models.DateField(null=True, blank=True, help_text="Empty = no start limit")
    end_date = models.DateField(null=True, blank=True, help_text="Empty = no end limit")
    weekdays = models.CharField(max_length=20, blank=True, help_text="Comma separated 0-6 (Mon=0); empty = every day")
    ticket_type = models.ForeignKey(
        TicketType, on_delete=models.CASCADE, null=True, blank=True, related_name="price_rules",
        help_text="Empty = every ticket type",
    )
    adjustment_type = models.CharField(max_length=12, choices=Adjustment.choices, default=Adjustment.PERCENT)
    value = models.DecimalField(
        max_digits=8, decimal_places=2,
        help_text="Percent: +25 = 25% more, -20 = 20% off. Fixed price: the ticket price in rupees",
    )
    priority = models.SmallIntegerField(default=0, help_text="Higher wins when several rules match")
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-priority", "-id"]

    @property
    def weekday_list(self):
        return [int(d) for d in self.weekdays.split(",") if d.strip().isdigit()]

    def matches(self, ticket_type, day):
        if not self.is_active:
            return False
        if self.ticket_type_id and self.ticket_type_id != ticket_type.id:
            return False
        if self.start_date and day < self.start_date:
            return False
        if self.end_date and day > self.end_date:
            return False
        days = self.weekday_list
        return not days or day.weekday() in days

    def apply(self, price):
        from decimal import ROUND_HALF_UP, Decimal

        if self.adjustment_type == self.Adjustment.FIXED_PRICE:
            new = Decimal(self.value)
        else:
            new = Decimal(price) * (Decimal(100) + Decimal(self.value)) / Decimal(100)
        return max(new, Decimal(0)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

    def __str__(self):
        return f"{self.museum.name}: {self.name}"


class Gate(models.Model):
    """An entry gate of a place (e.g. "East gate", "West gate"). Gate scans record which gate admitted them."""

    museum = models.ForeignKey(Museum, on_delete=models.CASCADE, related_name="gates")
    name = models.CharField(max_length=60)
    is_active = models.BooleanField(default=True)
    sort_order = models.PositiveSmallIntegerField(default=0)

    class Meta:
        ordering = ["sort_order", "name", "id"]
        unique_together = ("museum", "name")

    def __str__(self):
        return f"{self.museum.name} - {self.name}"


class SiteSettings(models.Model):
    """Site-wide switches admins change in Admin -> Settings (one row, id 1).

    A kind of booking is open at a place only when BOTH its site-wide switch and the place's own switch
    (`Museum.allow_individual` / `allow_groups`) are on; see museums.groups.block_reason.
    """

    individual_bookings_enabled = models.BooleanField(default=True, help_text="Individual entry tickets bought online")
    group_bookings_enabled = models.BooleanField(default=True, help_text="Instant group bookings (21-60 people)")
    group_requests_enabled = models.BooleanField(default=True, help_text="Group requests for 61+ people")
    school_trips_enabled = models.BooleanField(default=True, help_text="New school trip requests")
    events_enabled = models.BooleanField(default=True, help_text="Tickets for events and shows")
    passes_enabled = models.BooleanField(default=True, help_text="Combo pass sales")
    paused_message = models.CharField(
        max_length=200, blank=True,
        help_text="Shown to visitors while something is switched off, e.g. 'Paused during the festival week'",
    )
    # Footer text. Empty = the standard wording (translated into every language); filled = shown exactly as typed.
    footer_brand = models.CharField(max_length=80, blank=True, help_text="e.g. Ancient Antiquity")
    footer_tagline = models.CharField(max_length=200, blank=True, help_text="Line under the name in the footer")
    footer_copyright = models.CharField(
        max_length=200, blank=True,
        help_text="e.g. '© {year} Ancient Antiquity Heritage Pvt. Ltd.' ({year} = the current year) or a fixed year",
    )
    updated_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+")
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = verbose_name_plural = "Site settings"

    def __str__(self):
        return "Site settings"

    @classmethod
    def load(cls):
        from django.core.cache import cache

        obj = cache.get("site_settings")
        if obj is None:
            obj, _ = cls.objects.get_or_create(pk=1)
            cache.set("site_settings", obj, 60)
        return obj

    def save(self, *args, **kwargs):
        from django.core.cache import cache

        self.pk = 1
        super().save(*args, **kwargs)
        cache.delete("site_settings")
