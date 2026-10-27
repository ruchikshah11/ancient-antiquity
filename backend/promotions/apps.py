from django.apps import AppConfig


class PromotionsConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'promotions'
    verbose_name = "Promotions"

    def ready(self):
        from django.db.models.signals import post_save

        from bookings.models import Booking

        from .signals import release_voucher_on_end

        post_save.connect(release_voucher_on_end, sender=Booking, dispatch_uid="promotions_release_voucher")
