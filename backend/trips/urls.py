from django.urls import path
from rest_framework.routers import DefaultRouter

from . import views

router = DefaultRouter()
router.register("trips", views.TripViewSet, basename="trip")

urlpatterns = [
    path("places/geo/", views.GeoPlacesView.as_view(), name="places-geo"),
    path("places/nearby/", views.NearbyPlacesView.as_view(), name="places-nearby"),
    path("favourites/", views.FavouriteListView.as_view(), name="favourites"),
    path("favourites/ids/", views.FavouriteIdsView.as_view(), name="favourite-ids"),
    path("favourites/<slug:slug>/", views.FavouriteDetailView.as_view(), name="favourite-detail"),
] + router.urls
