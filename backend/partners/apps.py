from django.apps import AppConfig


class PartnersConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'partners'
    verbose_name = 'Partners (tour operators, settlements, kiosks)'

    def ready(self):
        from . import signals  # noqa: F401
