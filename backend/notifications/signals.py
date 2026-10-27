"""Send booking emails/SMS when a booking's status changes.

Hooked on the model rather than the views so that every path (online payment, Razorpay webhook,
counter sale, admin cancellation) notifies the visitor the same way.
"""
import logging

from django.db import transaction
from django.db.models.signals import post_save, pre_save

logger = logging.getLogger(__name__)

# Statuses from which reaching "confirmed" counts as a fresh confirmation (None = brand-new booking).
CONFIRMABLE_FROM = {None, "pending", "expired"}


def remember_old_status(sender, instance, **kwargs):
    if instance.pk:
        instance._old_status = sender.objects.filter(pk=instance.pk).values_list("status", flat=True).first()
    else:
        instance._old_status = None


def notify_status_change(sender, instance, created, **kwargs):
    from . import services

    old = getattr(instance, "_old_status", None)
    new = instance.status
    if old == new:
        return
    booking_id = instance.pk
    if new == "confirmed" and old in CONFIRMABLE_FROM:
        # on_commit: no mail for a transaction that later rolls back, and the refetch sees committed data.
        transaction.on_commit(lambda: services.send_booking_confirmed(booking_id))
    elif new == "cancelled":
        # Refund fields are saved after the status in cancel_booking(), so read them after commit.
        transaction.on_commit(lambda: services.send_booking_cancelled(booking_id))


def connect():
    pre_save.connect(remember_old_status, sender="bookings.Booking", dispatch_uid="notifications_pre_save")
    post_save.connect(notify_status_change, sender="bookings.Booking", dispatch_uid="notifications_post_save")
