from django.urls import path
from rest_framework.routers import SimpleRouter

from . import views

router = SimpleRouter()
router.register("admin/promo-codes", views.PromoCodeViewSet, basename="promo-code")
router.register("admin/gift-vouchers", views.GiftVoucherViewSet, basename="gift-voucher")

urlpatterns = [
    path("bookings/<str:reference>/apply-code/", views.ApplyCodeView.as_view(), name="booking-apply-code"),
    path("bookings/<str:reference>/remove-code/", views.RemoveCodeView.as_view(), name="booking-remove-code"),
] + router.urls
