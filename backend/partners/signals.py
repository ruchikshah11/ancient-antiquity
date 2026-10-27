"""Keep tour operator balances in step with their bookings, whichever code path changes a booking."""
from django.db.models.signals import post_save
from django.dispatch import receiver

from bookings.models import Booking


@receiver(post_save, sender=Booking, dispatch_uid="partners_agent_balance")
def agent_booking_changed(sender, instance, **kwargs):
    if not instance.agent_id:
        return
    from .models import AgentProfile
    from .services import recalc_balance

    profile = AgentProfile.objects.filter(user_id=instance.agent_id).first()
    if profile:
        recalc_balance(profile)
