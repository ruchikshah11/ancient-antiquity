from django.conf import settings
from django.db import models


class ContactMessage(models.Model):
    """A message sent from the public Contact page (support, refunds, place corrections...)."""

    class Topic(models.TextChoices):
        BOOKING = "booking", "Booking"
        REFUND = "refund", "Refund"
        GROUP = "group", "Group visit"
        DATA = "data", "Incorrect place information"
        PARTNERSHIP = "partnership", "Partnership"
        OTHER = "other", "Other"

    class Status(models.TextChoices):
        NEW = "new", "New"
        IN_PROGRESS = "in_progress", "In progress"
        CLOSED = "closed", "Closed"

    name = models.CharField(max_length=120)
    email = models.EmailField()
    phone = models.CharField(max_length=20, blank=True)
    topic = models.CharField(max_length=20, choices=Topic.choices, default=Topic.OTHER)
    place_slug = models.SlugField(max_length=220, blank=True, help_text="Place the message is about (optional)")
    booking_reference = models.CharField(max_length=40, blank=True)
    message = models.TextField(max_length=5000)
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.NEW, db_index=True)
    admin_note = models.TextField(blank=True, help_text="Internal note, never shown to the sender")
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="contact_messages"
    )
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.get_topic_display()} from {self.name} <{self.email}>"
