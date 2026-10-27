from rest_framework.routers import SimpleRouter

from . import views

router = SimpleRouter()
router.register("membership-plans", views.MembershipPlanViewSet, basename="membership-plan")
router.register("memberships", views.MembershipViewSet, basename="membership")
router.register("admin/membership-plans", views.AdminMembershipPlanViewSet, basename="admin-membership-plan")
router.register("admin/memberships", views.AdminMembershipViewSet, basename="admin-membership")

urlpatterns = router.urls
