"""Add-on stock: how many of an add-on are taken on a visit date."""
from django.db.models import Sum


def sold_quantity(addon, visit_date, exclude_booking=None):
    """Units of `addon` held on `visit_date` by bookings that still hold their seats (paid, or pending in hold).

    Cancelled and expired bookings give their add-ons back automatically.
    """
    from bookings.models import Booking, BookingAddOn
    from bookings.services import seat_holding_filter

    holding = Booking.objects.filter(visit_date=visit_date).filter(seat_holding_filter())
    lines = BookingAddOn.objects.filter(addon=addon, booking__in=holding)
    if exclude_booking is not None:
        lines = lines.exclude(booking=exclude_booking)
    return lines.aggregate(n=Sum("quantity"))["n"] or 0


def remaining_on(addon, visit_date, exclude_booking=None):
    """Units still available on `visit_date` (None = unlimited)."""
    if addon.daily_stock is None:
        return None
    return max(addon.daily_stock - sold_quantity(addon, visit_date, exclude_booking), 0)
