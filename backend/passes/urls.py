from rest_framework.routers import SimpleRouter

from . import views

router = SimpleRouter()
router.register("passes", views.ComboPassViewSet, basename="combo-pass")
router.register("pass-orders", views.PassOrderViewSet, basename="pass-order")
router.register("admin/passes", views.AdminComboPassViewSet, basename="admin-combo-pass")
router.register("admin/pass-orders", views.AdminPassOrderViewSet, basename="admin-pass-order")

urlpatterns = router.urls
