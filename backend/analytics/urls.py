from django.urls import path

from .views import FunnelEventView, FunnelReportView, UnsubscribeView

urlpatterns = [
    path("analytics/events/", FunnelEventView.as_view(), name="analytics-events"),
    path("analytics/unsubscribe/<str:token>/", UnsubscribeView.as_view(), name="analytics-unsubscribe"),
    path("admin/funnel/", FunnelReportView.as_view(), name="admin-funnel"),
]
