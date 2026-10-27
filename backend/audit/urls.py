from django.urls import path

from . import views

urlpatterns = [
    path("admin/audit/", views.AuditEntryListView.as_view(), name="admin-audit"),
]
