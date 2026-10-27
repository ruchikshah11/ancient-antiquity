"""Export jobs API: /api/admin/exports/ (list mine, start one), /<id>/ (status, delete), /<id>/download/."""
from datetime import timedelta

from django.conf import settings
from django.http import FileResponse, Http404
from django.utils import timezone
from rest_framework import serializers, status
from rest_framework.exceptions import ValidationError
from rest_framework.response import Response
from rest_framework.views import APIView

from accounts.permissions import IsPanelUser

from . import exports
from .models import ExportJob


class ExportJobSerializer(serializers.ModelSerializer):
    kind_label = serializers.CharField(source="get_kind_display", read_only=True)
    status_label = serializers.CharField(source="get_status_display", read_only=True)
    download_url = serializers.SerializerMethodField()

    class Meta:
        model = ExportJob
        fields = (
            "id", "kind", "kind_label", "filters", "status", "status_label", "row_count", "total_rows",
            "file_name", "file_size", "note", "error", "created_at", "started_at", "finished_at", "download_url",
        )

    def get_download_url(self, job):
        # Relative to the API root; the file is only served with the owner's token (no public media URL).
        return f"/admin/exports/{job.pk}/download/" if job.status == ExportJob.Status.DONE else None


class ExportJobListView(APIView):
    permission_classes = [IsPanelUser]

    def get(self, request):
        exports.cleanup_expired()
        # Restart my jobs that a server restart left behind (running without heartbeat, or never started).
        exports.requeue_stale()
        forgotten = ExportJob.objects.filter(
            user=request.user, status=ExportJob.Status.PENDING, created_at__lt=timezone.now() - timedelta(seconds=30),
        )
        for job_id in forgotten.values_list("pk", flat=True):
            exports.start(job_id)
        jobs = ExportJob.objects.filter(user=request.user)[:50]
        return Response({
            "results": ExportJobSerializer(jobs, many=True).data,
            "keep_days": settings.EXPORT_KEEP_DAYS,
            "pdf_max_rows": settings.EXPORT_PDF_MAX_ROWS,
        })

    def post(self, request):
        kind = request.data.get("kind")
        if kind not in ExportJob.Kind.values:
            raise ValidationError({"kind": f"Choose one of: {', '.join(ExportJob.Kind.values)}."})
        filters = exports.clean_filters(request.user, kind, request.data.get("filters"))
        active = ExportJob.objects.filter(
            user=request.user, status__in=[ExportJob.Status.PENDING, ExportJob.Status.RUNNING]
        ).count()
        if active >= exports.MAX_ACTIVE_PER_USER:
            raise ValidationError({"detail": "You already have exports running. Wait for one to finish first."})
        job = ExportJob.objects.create(user=request.user, kind=kind, filters=filters)
        if kind in exports.USER_KINDS:
            from audit.services import record

            # Personal data leaving the system: keep a trail of who exported what (as the Users page does).
            record(request, "users.export", user=request.user,
                   object_repr=f"{kind} (background) · {exports._describe_users(filters)}")
        exports.start(job.pk)
        job.refresh_from_db()
        return Response(ExportJobSerializer(job).data, status=status.HTTP_201_CREATED)


def _own_job(request, pk):
    job = ExportJob.objects.filter(pk=pk, user=request.user).first()
    if job is None:
        raise Http404
    return job


class ExportJobDetailView(APIView):
    permission_classes = [IsPanelUser]

    def get(self, request, pk):
        return Response(ExportJobSerializer(_own_job(request, pk)).data)

    def delete(self, request, pk):
        job = _own_job(request, pk)
        if job.status == ExportJob.Status.RUNNING:
            raise ValidationError({"detail": "This export is still running."})
        exports.delete_file(job)
        job.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


class ExportJobDownloadView(APIView):
    permission_classes = [IsPanelUser]

    def get(self, request, pk):
        job = _own_job(request, pk)
        if job.status != ExportJob.Status.DONE or not job.file_path:
            raise Http404
        path = exports.exports_dir() / job.file_path
        if not path.is_file():
            raise Http404
        content_type = {
            "csv": "text/csv; charset=utf-8",
            "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            "pdf": "application/pdf",
        }[exports._ext(job.kind)]
        # Streams the file from disk in blocks.
        return FileResponse(open(path, "rb"), as_attachment=True, filename=job.file_name, content_type=content_type)
