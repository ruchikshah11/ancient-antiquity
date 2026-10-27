"""Ticket add-ons a place sells with its entry tickets: audio guides, camera permits, guided tours, wheelchairs...

Visitors choose them at checkout while the booking is still pending payment (bookings.BookingAddOn holds
the chosen lines with a price snapshot). An add-on with a daily_stock (e.g. 5 wheelchairs) can only be sold
that many times per visit date across bookings that still hold their seats.
"""
from decimal import Decimal

from django.core.validators import MinValueValidator
from django.db import models

from museums.models import Museum


class AddOn(models.Model):
    class Kind(models.TextChoices):
        AUDIO_GUIDE = "audio_guide", "Audio guide"
        CAMERA = "camera", "Camera permit"
        VIDEO = "video", "Video camera permit"
        GUIDED_TOUR = "guided_tour", "Guided tour"
        PARKING = "parking", "Parking"
        WHEELCHAIR = "wheelchair", "Wheelchair"
        LOCKER = "locker", "Locker / cloakroom"
        OTHER = "other", "Other"

    class Per(models.TextChoices):
        PERSON = "person", "Per person"
        BOOKING = "booking", "Per booking"

    # Bootstrap Icons (1.5) shown next to each kind on checkout, the ticket and the place page.
    ICONS = {
        Kind.AUDIO_GUIDE: "headphones",
        Kind.CAMERA: "camera",
        Kind.VIDEO: "camera-video",
        Kind.GUIDED_TOUR: "signpost-2",
        Kind.PARKING: "cone-striped",
        Kind.WHEELCHAIR: "life-preserver",
        Kind.LOCKER: "safe",
        Kind.OTHER: "plus-circle",
    }

    museum = models.ForeignKey(Museum, on_delete=models.CASCADE, related_name="addons")
    name = models.CharField(max_length=80)
    description = models.CharField(max_length=255, blank=True)
    kind = models.CharField(max_length=12, choices=Kind.choices, default=Kind.OTHER)
    price = models.DecimalField(max_digits=8, decimal_places=2, default=0, validators=[MinValueValidator(Decimal("0"))])
    per = models.CharField(max_length=8, choices=Per.choices, default=Per.BOOKING)
    max_per_booking = models.PositiveSmallIntegerField(
        null=True, blank=True, help_text="Most a booking may take (empty: one per visitor, or 1 if priced per booking)"
    )
    daily_stock = models.PositiveIntegerField(
        null=True, blank=True, help_text="How many can be sold per visit date (empty: unlimited)"
    )
    is_active = models.BooleanField(default=True)
    sort = models.PositiveSmallIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["sort", "id"]
        verbose_name = "add-on"

    def __str__(self):
        return f"{self.name} ({self.museum.name})"

    @property
    def icon(self):
        return self.ICONS.get(self.kind, "plus-circle")

    def quantity_limit(self, visitors):
        """Most of this add-on one booking of `visitors` people may take."""
        if self.per == self.Per.PERSON:
            return min(visitors, self.max_per_booking) if self.max_per_booking else visitors
        return self.max_per_booking or 1
