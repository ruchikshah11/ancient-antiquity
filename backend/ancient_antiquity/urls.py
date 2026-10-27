from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import include, path

admin.site.site_header = "Ancient Antiquity Administration"
admin.site.site_title = "Ancient Antiquity"
admin.site.index_title = "Museum Booking Management"

urlpatterns = [
    path("django-admin/", admin.site.urls),
    path("api/auth/", include("accounts.urls")),
    path("api/", include("museums.urls")),
    path("api/", include("bookings.urls")),
    path("api/", include("notifications.urls")),
    path("api/", include("grouprequests.urls")),
    path("api/", include("support.urls")),
    path("api/", include("promotions.urls")),
    path("api/", include("trips.urls")),
    path("api/", include("audit.urls")),
    path("api/", include("passes.urls")),
    path("api/", include("events.urls")),
    path("api/", include("partners.urls")),
    path("api/", include("assistant.urls")),
    path("api/", include("analytics.urls")),
    path("api/", include("memberships.urls")),
    path("api/", include("schools.urls")),
    path("api/", include("donations.urls")),
    path("api/", include("addons.urls")),
    path("api/", include("insights.urls")),
    path("api/", include("stats.urls")),
]

if settings.DEBUG:  # in production the web server (nginx) serves /media/
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
