from django.urls import path
from rest_framework.routers import SimpleRouter

from . import views

router = SimpleRouter()
router.register("donations", views.DonationViewSet, basename="donation")
router.register("admin/donations", views.AdminDonationViewSet, basename="admin-donation")

urlpatterns = [
    path("fx-rates/", views.fx_rates, name="fx-rates"),
] + router.urls
