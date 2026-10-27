"""Tell waitlisted visitors when a booking releases its seats (cancelled, or its unpaid hold expired).

Bulk expiry in bookings.services.expire_stale_bookings() uses queryset.update(), which fires no signals,
so that function calls events.services.notify_for_bookings() itself.
"""
from django.db import transaction
from django.db.models.signals import post_save, pre_save

RELEASED = {"cancelled", "expired"}
HELD = {"pending", "confirmed", "checked_in"}


def remember_status(sender, instance, **kwargs):
    if instance.pk:
        instance._waitlist_old_status = (
            sender.objects.filter(pk=instance.pk).values_list("status", flat=True).first()
        )
    else:
        instance._waitlist_old_status = None


def booking_saved(sender, instance, created, **kwargs):
    from . import services

    old = getattr(instance, "_waitlist_old_status", None)
    if created:
        services.mark_booked_for(instance)
        return
    if instance.status in RELEASED and old in HELD:
        row = (instance.slot_id, instance.event_session_id, instance.visit_date)
        transaction.on_commit(lambda: services.notify_for_bookings([row]))


def connect():
    pre_save.connect(remember_status, sender="bookings.Booking", dispatch_uid="events_waitlist_pre_save")
    post_save.connect(booking_saved, sender="bookings.Booking", dispatch_uid="events_waitlist_post_save")
