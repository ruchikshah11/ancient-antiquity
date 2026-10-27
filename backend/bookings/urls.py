from django.urls import path
from rest_framework.routers import DefaultRouter

from . import reports, views

router = DefaultRouter()
router.register("bookings", views.BookingViewSet, basename="booking")
router.register("admin/gates", views.GateViewSet, basename="gate")

urlpatterns = [
    path("admin/dashboard/", views.DashboardView.as_view(), name="dashboard"),
    path("admin/occupancy/", views.OccupancyView.as_view(), name="occupancy"),
    path("admin/reports/summary/", reports.ReportSummaryView.as_view(), name="report-summary"),
    path("admin/reports/bookings.csv", reports.BookingsCsvView.as_view(), name="report-bookings-csv"),
    path("admin/reports/bookings.xlsx", reports.BookingsXlsxView.as_view(), name="report-bookings-xlsx"),
    path("payments/razorpay/webhook/", views.RazorpayWebhookView.as_view(), name="razorpay-webhook"),
    path("payments/config/", views.PaymentConfigView.as_view(), name="payment-config"),
] + router.urls
