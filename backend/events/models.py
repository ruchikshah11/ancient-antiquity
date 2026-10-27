"""Ticketed events and shows at a place (light & sound shows, night viewings, walks...) and the waitlist.

Events have their own dated sessions with their own capacity, separate from the place's daily entry slots.
Event tickets are ordinary bookings (Booking.event_session set, Booking.slot empty), so payment, cancellation,
refunds, invoices and gate check-in all reuse the bookings app.
"""
import datetime

from django.conf import settings
from django.core.validators import MinValueValidator
from django.db import models
from django.utils import timezone
from django.utils.text import slugify

from museums.models import Museum, TimeSlot


class Event(models.Model):
    class Kind(models.TextChoices):
        LIGHT_SOUND = "light_sound", "Light & sound show"
        NIGHT_VIEWING = "night_viewing", "Night viewing"
        EXHIBITION = "exhibition", "Exhibition"
        HERITAGE_WALK = "heritage_walk", "Heritage walk"
        WORKSHOP = "workshop", "Workshop"
        OTHER = "other", "Other"

    museum = models.ForeignKey(Museum, on_delete=models.CASCADE, related_name="events")
    title = models.CharField(max_length=150)
    slug = models.SlugField(max_length=170, unique=True, blank=True)
    kind = models.CharField(max_length=15, choices=Kind.choices, default=Kind.OTHER, db_index=True)
    description = models.TextField(blank=True)
    image_url = models.URLField(max_length=500, blank=True)
    language = models.CharField(max_length=60, blank=True, help_text="e.g. Hindi, English")
    duration_minutes = models.PositiveIntegerField(default=60, validators=[MinValueValidator(1)])
    is_active = models.BooleanField(default=True)
    featured = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-featured", "title"]

    def __str__(self):
        return self.title

    def save(self, *args, **kwargs):
        if not self.slug:
            base = slugify(self.title)[:160] or "event"
            slug, n = base, 2
            while Event.objects.filter(slug=slug).exclude(pk=self.pk).exists():
                slug, n = f"{base}-{n}", n + 1
            self.slug = slug
        super().save(*args, **kwargs)


class EventSession(models.Model):
    """One dated performance/run of an event, with its own capacity."""

    event = models.ForeignKey(Event, on_delete=models.CASCADE, related_name="sessions")
    date = models.DateField(db_index=True)
    start_time = models.TimeField()
    end_time = models.TimeField()
    capacity = models.PositiveIntegerField(validators=[MinValueValidator(1)])
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["date", "start_time"]

    def __str__(self):
        return f"{self.event.title} {self.date:%d %b %Y} {self.start_time:%H:%M}"

    @property
    def starts_at(self):
        return timezone.make_aware(datetime.datetime.combine(self.date, self.start_time))


class EventPrice(models.Model):
    """A ticket category for an event, e.g. Adult, Child, Foreign national."""

    event = models.ForeignKey(Event, on_delete=models.CASCADE, related_name="prices")
    name = models.CharField(max_length=60)
    price = models.DecimalField(max_digits=8, decimal_places=2, validators=[MinValueValidator(0)])
    sort = models.PositiveSmallIntegerField(default=0)

    class Meta:
        ordering = ["sort", "id"]

    def __str__(self):
        return f"{self.event.title} - {self.name}"


class WaitlistEntry(models.Model):
    """A visitor waiting for seats in a full entry slot (slot + visit_date) or a full event session."""

    class Status(models.TextChoices):
        WAITING = "waiting", "Waiting"
        NOTIFIED = "notified", "Notified"
        BOOKED = "booked", "Booked"
        EXPIRED = "expired", "Expired"

    CHANNELS = ("email", "sms", "whatsapp", "push")

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="waitlist_entries")
    museum = models.ForeignKey(Museum, on_delete=models.CASCADE, related_name="waitlist_entries")
    slot = models.ForeignKey(TimeSlot, on_delete=models.CASCADE, null=True, blank=True, related_name="waitlist_entries")
    event_session = models.ForeignKey(
        EventSession, on_delete=models.CASCADE, null=True, blank=True, related_name="waitlist_entries"
    )
    visit_date = models.DateField(db_index=True)
    quantity = models.PositiveSmallIntegerField(validators=[MinValueValidator(1)])
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.WAITING, db_index=True)
    notify_channels = models.JSONField(default=list, blank=True, help_text='e.g. ["email", "sms"]; empty = all')
    created_at = models.DateTimeField(auto_now_add=True)
    notified_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["created_at", "id"]  # FIFO
        verbose_name_plural = "waitlist entries"

    def __str__(self):
        return f"{self.user} x{self.quantity} {self.museum} {self.visit_date} ({self.status})"

    def wants(self, channel):
        return not self.notify_channels or channel in self.notify_channels
