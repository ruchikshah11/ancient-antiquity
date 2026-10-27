from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models

MAX_TRIP_DAYS = 60
MAX_STOPS_PER_TRIP = 100


class Favourite(models.Model):
    """A place a visitor saved (the heart on place cards)."""

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="favourites")
    museum = models.ForeignKey("museums.Museum", on_delete=models.CASCADE, related_name="favourited_by")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at", "-id"]
        unique_together = ("user", "museum")

    def __str__(self):
        return f"{self.user} ♥ {self.museum}"


class Trip(models.Model):
    """A personal itinerary: places grouped by day."""

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="trips")
    title = models.CharField(max_length=120)
    start_date = models.DateField(null=True, blank=True)
    end_date = models.DateField(null=True, blank=True)
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at", "-id"]

    def clean(self):
        if self.start_date and self.end_date and self.end_date < self.start_date:
            raise ValidationError({"end_date": "End date must be on or after the start date."})

    @property
    def day_count(self):
        if self.start_date and self.end_date:
            return (self.end_date - self.start_date).days + 1
        return None

    def __str__(self):
        return self.title


class TripStop(models.Model):
    trip = models.ForeignKey(Trip, on_delete=models.CASCADE, related_name="stops")
    museum = models.ForeignKey("museums.Museum", on_delete=models.CASCADE, related_name="trip_stops")
    day = models.PositiveSmallIntegerField(default=1, validators=[MinValueValidator(1), MaxValueValidator(MAX_TRIP_DAYS)])
    order = models.PositiveSmallIntegerField(default=0)
    planned_time = models.TimeField(null=True, blank=True)
    notes = models.CharField(max_length=300, blank=True)

    class Meta:
        ordering = ["day", "order", "id"]

    def __str__(self):
        return f"{self.trip} day {self.day}: {self.museum}"
