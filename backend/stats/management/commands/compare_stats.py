import datetime
import time

from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone
from rest_framework.test import APIRequestFactory, force_authenticate

from accounts.models import User
from bookings.reports import ReportSummaryView
from bookings.views import DashboardView
from museums.models import Museum
from stats import legacy


def call(view, user, path, params=None):
    request = APIRequestFactory().get(path, params or {})
    force_authenticate(request, user=user)
    started = time.monotonic()
    response = view.as_view()(request)
    return response, time.monotonic() - started


class Command(BaseCommand):
    help = ("One-off check: dashboard and report figures from stats.DailyStat against the old live booking queries, "
            "for several date ranges, a place and a staff user. Exits with an error on any difference.")

    def handle(self, *args, **options):
        today = timezone.localdate()
        admin = User.objects.filter(role=User.Role.ADMIN, is_active=True).order_by("id").first()
        if not admin:
            raise CommandError("No admin user.")
        busiest = Museum.objects.order_by("-id").first()
        staff = User.objects.filter(role=User.Role.STAFF, is_active=True, assigned_museums__isnull=False).first()
        d = datetime.timedelta
        ranges = [
            (today, today), (today - d(days=6), today), (today - d(days=29), today),
            (datetime.date(today.year, 3, 1), datetime.date(today.year, 3, 31)), (today - d(days=365), today),
        ]
        cases = [(admin, a, b, None) for a, b in ranges] + [(admin, today - d(days=89), today, busiest)]
        if staff:
            cases.append((staff, today - d(days=29), today, None))
        problems = 0
        for user, a, b, museum in cases:
            params = {"from": str(a), "to": str(b)}
            if museum:
                params["museum"] = museum.slug
            response, took = call(ReportSummaryView, user, "/api/admin/reports/summary/", params)
            started = time.monotonic()
            old = legacy.report(user, a, b, museum)
            old_took = time.monotonic() - started
            diff = legacy.differences({k: response.data[k] for k in old}, old)
            problems += len(diff)
            label = f"report {a}..{b} {user.email}{' @' + museum.slug if museum else ''}"
            self.stdout.write(f"{label}: {'OK' if not diff else 'DIFF'}  stats {took * 1000:.0f} ms, live {old_took * 1000:.0f} ms")
            for line in diff[:10]:
                self.stdout.write(f"    {line}")
        for user in [admin] + ([staff] if staff else []):
            response, took = call(DashboardView, user, "/api/admin/dashboard/")
            started = time.monotonic()
            old = legacy.dashboard(user, today)
            old_took = time.monotonic() - started
            new = {k: response.data[k] for k in old}
            diff = legacy.differences(new, old)
            problems += len(diff)
            self.stdout.write(f"dashboard {user.email}: {'OK' if not diff else 'DIFF'}  stats {took * 1000:.0f} ms, live {old_took * 1000:.0f} ms")
            for line in diff[:10]:
                self.stdout.write(f"    {line}")
        if problems:
            raise CommandError(f"{problems} difference(s).")
        self.stdout.write(self.style.SUCCESS("All figures match."))
