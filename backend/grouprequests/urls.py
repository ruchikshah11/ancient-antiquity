from rest_framework.routers import SimpleRouter

from . import views

router = SimpleRouter()
router.register("group-requests", views.GroupRequestViewSet, basename="group-request")

urlpatterns = router.urls
