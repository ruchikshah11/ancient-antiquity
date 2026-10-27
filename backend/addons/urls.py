from django.urls import path
from rest_framework.routers import SimpleRouter

from . import views

router = SimpleRouter()
router.register("admin/addons", views.AdminAddOnViewSet, basename="admin-addon")

urlpatterns = [
    path("museums/<slug:slug>/addons/", views.MuseumAddOnsView.as_view(), name="museum-addons"),
] + router.urls
