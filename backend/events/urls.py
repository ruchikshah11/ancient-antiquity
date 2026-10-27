from django.urls import path
from rest_framework.routers import SimpleRouter

from . import views

router = SimpleRouter()
router.register("events", views.EventViewSet, basename="event")
router.register("waitlist", views.WaitlistViewSet, basename="waitlist")
router.register("admin/events", views.AdminEventViewSet, basename="admin-event")
router.register("admin/event-sessions", views.AdminEventSessionViewSet, basename="admin-event-session")
router.register("admin/event-prices", views.AdminEventPriceViewSet, basename="admin-event-price")

# The explicit path comes first so "bookings" is never read as an event slug.
urlpatterns = [
    path("events/bookings/", views.EventBookingView.as_view(), name="event-booking"),
] + router.urls
