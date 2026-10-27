from django.urls import path
from rest_framework.routers import SimpleRouter

from . import views

router = SimpleRouter()
router.register("admin/support-messages", views.AdminSupportMessageViewSet, basename="admin-support-message")

urlpatterns = [
    path("support/health/", views.HealthView.as_view(), name="support-health"),
    path("support/info/", views.SupportInfoView.as_view(), name="support-info"),
    path("support/contact/", views.ContactCreateView.as_view(), name="support-contact"),
] + router.urls
