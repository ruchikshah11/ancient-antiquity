from django.urls import path
from rest_framework.routers import SimpleRouter

from . import portal, views

router = SimpleRouter()
router.register("admin/agents", views.AdminAgentViewSet, basename="admin-agent")
router.register("admin/settlements", views.AdminSettlementViewSet, basename="admin-settlement")
router.register("admin/partner-accounts", views.AdminPartnerAccountViewSet, basename="partner-account")
router.register("admin/kiosks", views.AdminKioskViewSet, basename="admin-kiosk")
router.register("settlements", views.SettlementViewSet, basename="settlement")

urlpatterns = [
    path("agents/me/", views.AgentMeView.as_view(), name="agent-me"),
    path("agents/apply/", views.AgentApplyView.as_view(), name="agent-apply"),
    path("agents/bookings/", views.AgentBookingsView.as_view(), name="agent-bookings"),
    path("agents/bookings/<str:reference>/cancel/", views.AgentBookingCancelView.as_view(), name="agent-booking-cancel"),
    path("agents/statement/", views.AgentStatementView.as_view(), name="agent-statement"),
    path("settlements/export.csv", views.SettlementsCsvView.as_view(), name="settlements-csv"),
    path("kiosk/me/", views.KioskMeView.as_view(), name="kiosk-me"),
    path("kiosk/session/", views.KioskSessionView.as_view(), name="kiosk-session"),
    path("kiosk/bookings/", views.KioskBookingView.as_view(), name="kiosk-bookings"),
    # Read-only partner portal for a place's management (role partner).
    path("partner/me/", portal.PartnerMeView.as_view(), name="partner-me"),
    path("partner/overview/", portal.PartnerOverviewView.as_view(), name="partner-overview"),
    path("partner/trend/", portal.PartnerTrendView.as_view(), name="partner-trend"),
    path("partner/reviews/", portal.PartnerReviewsView.as_view(), name="partner-reviews"),
    path("partner/settlements/", portal.PartnerSettlementsView.as_view(), name="partner-settlements"),
] + router.urls
