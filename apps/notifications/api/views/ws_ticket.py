"""A ticket for opening the notifications socket from a browser (SEC-4)."""

from drf_spectacular.utils import extend_schema

from apps.common.base_views import BaseAPIView
from apps.common.responses import ApiResponse
from apps.notifications.api.serializers.ws_ticket import (
    WebSocketTicketSerializer,
)
from apps.notifications.services.ws_ticket_service import (
    WebSocketTicketService,
)


@extend_schema(
    tags=["Notifications"],
    summary="Ticket for the notifications socket",
    description=(
        "For browsers, which cannot send an Authorization header on a "
        "WebSocket handshake. Connect to /ws/notifications/?ticket=<ticket> "
        "within expires_in seconds; a ticket opens one socket. Fetch a new "
        "one for every reconnect. Native apps send the Authorization header "
        "instead and need no ticket."
    ),
    request=None,
    responses={200: WebSocketTicketSerializer},
)
class WebSocketTicketAPIView(BaseAPIView):

    service_class = WebSocketTicketService

    def post(self, request):
        return ApiResponse.success(
            data=WebSocketTicketSerializer(
                self.service.issue(request.user)
            ).data,
            message="Ticket issued.",
        )
