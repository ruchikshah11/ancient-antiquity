from . import services


def release_voucher_on_end(sender, instance, created=False, **kwargs):
    """Booking expired/cancelled: return its gift-voucher money when the rules say so (idempotent)."""
    if created or not instance.voucher_amount or instance.voucher_amount <= 0:
        return
    if services.voucher_refund_due(instance):
        services.release_for_booking(instance)
