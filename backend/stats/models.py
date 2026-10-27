"""Pre-calculated booking statistics per day, and background export jobs.

DailyStat holds one row per (day, place, channel, individual/group, status group). Each row carries two
kinds of figures for its day:

- by BOOKING (sale) date, i.e. bookings whose created_at falls on `date` in the site's time zone:
  bookings, visitors, revenue, refunds, discounts, add-ons, membership discounts, checked-in bookings;
- by VISIT date, i.e. bookings whose visit_date is `date`: visit_bookings, visit_visitors,
  visit_checked_in_visitors (the dashboard's "expected today" and "checked in today").

"revenue" is the sum of total_amount for the row's status group; reports read it from the PAID group only
(confirmed + checked in), exactly like bookings.views.PAID.
"""
from django.conf import settings
from django.db import models

from museums.models import Museum


class StatusGroup(models.TextChoices):
    PAID = "paid", "Paid (confirmed or checked in)"
    PENDING = "pending", "Pending payment"
    CANCELLED = "cancelled", "Cancelled"
    EXPIRED = "expired", "Expired"


class DailyStat(models.Model):
    date = models.DateField()
    museum = models.ForeignKey(Museum, on_delete=models.CASCADE, related_name="+")
    channel = models.CharField(max_length=10)
    is_group = models.BooleanField()
    status_group = models.CharField(max_length=10, choices=StatusGroup.choices)

    # By booking (created) date
    bookings = models.PositiveIntegerField(default=0)
    checked_in_bookings = models.PositiveIntegerField(default=0, help_text="Of `bookings`, those checked in")
    visitors = models.PositiveIntegerField(default=0)
    revenue = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    refunds = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    discounts = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    addons = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    membership_discounts = models.DecimalField(max_digits=14, decimal_places=2, default=0)

    # By visit date
    visit_bookings = models.PositiveIntegerField(default=0)
    visit_visitors = models.PositiveIntegerField(default=0)
    visit_checked_in_visitors = models.PositiveIntegerField(default=0)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["date", "museum", "channel", "is_group", "status_group"], name="dailystat_unique_key",
            ),
        ]
        indexes = [
            models.Index(fields=["status_group", "date"], name="dailystat_group_date_idx"),
            models.Index(fields=["museum", "date"], name="dailystat_museum_date_idx"),
            # Covering index for the dashboard's all-time GROUP BY (read without touching the table).
            models.Index(
                fields=["museum", "channel", "is_group", "status_group", "bookings", "checked_in_bookings",
                        "visitors", "revenue"],
                name="dailystat_dashboard_idx",
            ),
        ]

    def __str__(self):
        return f"{self.date} {self.museum_id} {self.channel} {'group' if self.is_group else 'individual'} {self.status_group}"


class StatDay(models.Model):
    """Bookkeeping per day: when its DailyStat rows were computed and whether a booking changed since."""

    date = models.DateField(unique=True)
    refreshed_at = models.DateTimeField(null=True, blank=True)
    dirty_since = models.DateTimeField(null=True, blank=True, db_index=True)

    def __str__(self):
        return f"{self.date} ({'dirty' if self.dirty_since else 'fresh'})"


class ExportJob(models.Model):
    class Kind(models.TextChoices):
        BOOKINGS_CSV = "bookings_csv", "Bookings (CSV)"
        BOOKINGS_XLSX = "bookings_xlsx", "Bookings (Excel)"
        BOOKINGS_PDF = "bookings_pdf", "Bookings (PDF)"
        USERS_CSV = "users_csv", "Users (CSV)"
        USERS_XLSX = "users_xlsx", "Users (Excel)"
        USERS_PDF = "users_pdf", "Users (PDF)"

    class Status(models.TextChoices):
        PENDING = "pending", "Waiting"
        RUNNING = "running", "Running"
        DONE = "done", "Ready"
        FAILED = "failed", "Failed"
        EXPIRED = "expired", "Expired"

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="export_jobs")
    kind = models.CharField(max_length=16, choices=Kind.choices)
    filters = models.JSONField(default=dict, blank=True)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.PENDING, db_index=True)
    row_count = models.PositiveIntegerField(default=0)
    total_rows = models.PositiveIntegerField(null=True, blank=True, help_text="Rows matching the filters")
    file_name = models.CharField(max_length=200, blank=True, help_text="Download name")
    file_path = models.CharField(max_length=300, blank=True, help_text="Relative to EXPORTS_DIR (private)")
    file_size = models.PositiveBigIntegerField(default=0)
    note = models.CharField(max_length=300, blank=True)
    error = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    started_at = models.DateTimeField(null=True, blank=True)
    heartbeat_at = models.DateTimeField(null=True, blank=True)
    finished_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["user", "-created_at"], name="exportjob_user_created_idx")]

    def __str__(self):
        return f"{self.get_kind_display()} #{self.pk} ({self.status})"
