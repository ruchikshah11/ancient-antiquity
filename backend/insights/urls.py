from django.urls import path

from . import views

urlpatterns = [
    path("admin/pricing-suggestions/", views.PricingSuggestionsView.as_view(), name="pricing-suggestions"),
]
