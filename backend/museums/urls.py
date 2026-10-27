from django.urls import path
from rest_framework.routers import DefaultRouter

from . import views

router = DefaultRouter()
router.register("states", views.StateViewSet, basename="state")
router.register("cities", views.CityViewSet, basename="city")
router.register("categories", views.CategoryViewSet, basename="category")
router.register("museums", views.MuseumViewSet, basename="museum")
router.register("admin/reviews", views.AdminReviewViewSet, basename="admin-review")
router.register("admin/closures", views.AdminClosureViewSet, basename="admin-closure")
router.register("admin/price-rules", views.AdminPriceRuleViewSet, basename="admin-price-rule")

urlpatterns = [
    path("admin/staff/<int:user_id>/museums/", views.StaffMuseumsView.as_view(), name="staff-museums"),
    path("site-settings/", views.PublicSiteSettingsView.as_view(), name="site-settings"),
    path("admin/site-settings/", views.AdminSiteSettingsView.as_view(), name="admin-site-settings"),
] + router.urls
