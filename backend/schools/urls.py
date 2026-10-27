from django.urls import path
from rest_framework.routers import SimpleRouter

from . import views

router = SimpleRouter()
router.register("schools/trips", views.SchoolTripViewSet, basename="school-trip")
router.register("schools", views.SchoolViewSet, basename="school")

urlpatterns = [
    path("schools/mine/", views.MySchoolView.as_view(), name="my-school"),
    path("schools/estimate/", views.EstimateView.as_view(), name="school-estimate"),
] + router.urls
