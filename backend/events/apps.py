from django.apps import AppConfig


class EventsConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'events'
    verbose_name = "Events and waitlist"

    def ready(self):
        # Cancelled / expired bookings free seats for waitlisted visitors.
        from . import signals

        signals.connect()
