from django.urls import path

from . import views

urlpatterns = [
    path("notifications/bookings/<str:reference>/resend/", views.ResendConfirmationView.as_view(),
         name="notification-resend"),
    path("notifications/push/public-key/", views.PushPublicKeyView.as_view(), name="push-public-key"),
    path("notifications/push/subscribe/", views.PushSubscribeView.as_view(), name="push-subscribe"),
    path("notifications/push/unsubscribe/", views.PushUnsubscribeView.as_view(), name="push-unsubscribe"),
]
