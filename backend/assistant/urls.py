from django.urls import path

from .views import AssistantChatView, AssistantStatusView

urlpatterns = [
    path("assistant/status/", AssistantStatusView.as_view(), name="assistant-status"),
    path("assistant/chat/", AssistantChatView.as_view(), name="assistant-chat"),
]
