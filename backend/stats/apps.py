from django.apps import AppConfig


class StatsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "stats"
    verbose_name = "Daily statistics and exports"

    def ready(self):
        from . import signals  # noqa: F401  (marks stat days dirty when bookings change)
