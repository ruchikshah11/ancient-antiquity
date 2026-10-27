from django.urls import path

from . import views

urlpatterns = [
    path("admin/exports/", views.ExportJobListView.as_view(), name="export-jobs"),
    path("admin/exports/<int:pk>/", views.ExportJobDetailView.as_view(), name="export-job"),
    path("admin/exports/<int:pk>/download/", views.ExportJobDownloadView.as_view(), name="export-job-download"),
]
