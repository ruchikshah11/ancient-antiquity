from django.conf import settings
from django.core.validators import MaxValueValidator, MinValueValidator, RegexValidator
from django.db import models

from bookings.models import Booking
from museums.models import Museum, State

udise_validator = RegexValidator(r"^\d{11}$", "A UDISE code has exactly 11 digits.")
phone_validator = RegexValidator(r"^\+?[0-9]{10,13}$", "Enter a valid phone number.")


class School(models.Model):
    """A school registered by a teacher. Admins verify it before it can request class trips."""

    class Board(models.TextChoices):
        CBSE = "cbse", "CBSE"
        ICSE = "icse", "ICSE"
        STATE = "state", "State board"
        IB = "ib", "IB"
        OTHER = "other", "Other"

    class Status(models.TextChoices):
        PENDING = "pending", "Pending verification"
        VERIFIED = "verified", "Verified"
        REJECTED = "rejected", "Rejected"

    owner = models.OneToOneField(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="school",
        help_text="The teacher account that registered the school (one school per account)",
    )
    name = models.CharField(max_length=150)
    board = models.CharField(max_length=6, choices=Board.choices)
    udise_code = models.CharField(max_length=11, blank=True, validators=[udise_validator])
    address = models.CharField(max_length=255)
    city = models.CharField(max_length=80)
    state = models.ForeignKey(State, on_delete=models.PROTECT, related_name="schools")
    principal_name = models.CharField(max_length=120)
    phone = models.CharField(max_length=15, validators=[phone_validator])
    contact_name = models.CharField(max_length=120)
    contact_phone = models.CharField(max_length=15, validators=[phone_validator])
    contact_email = models.EmailField()

    status = models.CharField(max_length=8, choices=Status.choices, default=Status.PENDING, db_index=True)
    rejection_reason = models.TextField(blank=True)
    verified_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    verified_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.name}, {self.city}"

    @property
    def is_verified(self):
        return self.status == self.Status.VERIFIED


class SchoolTrip(models.Model):
    """A class visit requested by a verified school. Approval creates one pending group booking."""

    class Status(models.TextChoices):
        SUBMITTED = "submitted", "Submitted"
        APPROVED = "approved", "Approved"
        DECLINED = "declined", "Declined"
        CANCELLED = "cancelled", "Cancelled"
        COMPLETED = "completed", "Completed"

    class SlotPreference(models.TextChoices):
        MORNING = "morning", "Morning"
        AFTERNOON = "afternoon", "Afternoon"

    class Guide(models.TextChoices):
        NONE = "", "No guide"
        HINDI = "hi", "Hindi"
        ENGLISH = "en", "English"

    school = models.ForeignKey(School, on_delete=models.PROTECT, related_name="trips")
    requested_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="school_trips")
    museum = models.ForeignKey(Museum, on_delete=models.PROTECT, related_name="school_trips")
    preferred_date = models.DateField(db_index=True)
    alternative_date = models.DateField(null=True, blank=True)
    slot_preference = models.CharField(max_length=10, choices=SlotPreference.choices, default=SlotPreference.MORNING)
    grades = models.CharField(max_length=60, help_text="Class / grade(s), e.g. 6, 7A")
    students = models.PositiveIntegerField(validators=[MinValueValidator(10), MaxValueValidator(400)])
    young_students = models.PositiveIntegerField(
        default=0, help_text="Students young enough for the place's child ticket (e.g. below 15 at ASI sites)"
    )
    teachers = models.PositiveSmallIntegerField(validators=[MinValueValidator(1)])
    helpers = models.PositiveSmallIntegerField(default=0)
    accessibility_needs = models.TextField(blank=True)
    guide_language = models.CharField(max_length=2, choices=Guide.choices, blank=True, default="")
    notes = models.TextField(blank=True)

    status = models.CharField(max_length=10, choices=Status.choices, default=Status.SUBMITTED, db_index=True)
    estimated_amount = models.DecimalField(max_digits=10, decimal_places=2, default=0,
                                           help_text="Estimate shown to the teacher when submitting")
    quoted_amount = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    staff_note = models.TextField(blank=True, help_text="Note to the teacher or decline reason")
    approved_date = models.DateField(null=True, blank=True)
    booking = models.ForeignKey(Booking, on_delete=models.SET_NULL, null=True, blank=True, related_name="school_trips")
    decided_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    decided_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.reference} {self.school.name} -> {self.museum.name}"

    @property
    def reference(self):
        return f"ST-{self.pk:05d}" if self.pk else ""
