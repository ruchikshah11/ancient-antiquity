"""Mark DailyStat days dirty when a booking is saved or deleted (refreshed lazily on the next read).

Queryset .update()/.bulk_create() fire no signals: today/yesterday are refreshed on a timer anyway, the dashboard
marks the days of bookings it expires, and `manage.py rebuild_stats` fixes anything else.
"""
from django.db.models.signals import post_delete, post_init, post_save
from django.dispatch import receiver

from bookings.models import Booking

from .services import local_date, mark_dirty_after_commit


@receiver(post_init, sender=Booking)
def remember_visit_date(sender, instance, **kwargs):
    # A rescheduled booking must also refresh the day it moved away from.
    instance._stats_visit_date = instance.__dict__.get("visit_date")


def _dates(instance):
    dates = {instance.visit_date, getattr(instance, "_stats_visit_date", None)}
    if instance.created_at:
        dates.add(local_date(instance.created_at))
    return dates


@receiver(post_save, sender=Booking)
def booking_saved(sender, instance, raw=False, **kwargs):
    if raw:
        return
    mark_dirty_after_commit(_dates(instance))
    instance._stats_visit_date = instance.visit_date


@receiver(post_delete, sender=Booking)
def booking_deleted(sender, instance, **kwargs):
    mark_dirty_after_commit(_dates(instance))
