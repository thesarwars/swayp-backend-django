from django.urls import path

from apps.notifications.api.views.ws_ticket import WebSocketTicketAPIView

urlpatterns = [
    path(
        "/ws-ticket",
        WebSocketTicketAPIView.as_view(),
        name="notification-ws-ticket",
    ),
]
