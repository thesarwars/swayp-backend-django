"""WebSocket endpoint for live notifications (E8-S5).

    ws(s)://<host>/ws/notifications/
    Authorization: Bearer <access JWT>          native apps (DASH-3)

    ws(s)://<host>/ws/notifications/?ticket=<ticket>       browsers (SEC-4)

    ws(s)://<host>/ws/notifications/?token=<access JWT>    browsers, legacy

A native client sends the access token as an Authorization header, which
keeps it out of the URL and so out of proxy and server logs. The browser
WebSocket API cannot set headers, so a browser first asks
POST /notifications/ws-ticket for a single-use, 60-second ticket and puts
that in the URL instead: by the time a log is read, it is spent.
``?token=`` still works until the web app has moved to tickets; it puts a
live access token in the logs, so it is to be removed. Precedence: header,
then ticket, then token.

Read-only by design. The socket delivers; every action a user can take on a
notification (mark read, read all) stays on the authenticated REST API, so
there is exactly one code path that can mutate state and it is the one that is
already tested and rate-limited.
"""

import logging

from channels.db import database_sync_to_async
from channels.generic.websocket import AsyncJsonWebsocketConsumer
from django.conf import settings

from apps.notifications.realtime import group_for

logger = logging.getLogger(__name__)


@database_sync_to_async
def _user_from_token(raw_token):
    """Resolve an access token to an active user, or None.

    Every failure returns None rather than raising: an expired token is the
    ordinary case (a laptop waking from sleep), not an error worth a
    traceback in the log on every occurrence.
    """
    from rest_framework_simplejwt.exceptions import TokenError
    from rest_framework_simplejwt.tokens import AccessToken

    from apps.users.models.user import User

    if not raw_token:
        return None

    try:
        token = AccessToken(raw_token)
    except TokenError:
        return None

    from apps.authentication.authentication import session_is_live

    if not session_is_live(token):
        return None

    user = User.objects.filter(id=token.get("user_id"), is_active=True).first()

    return user


@database_sync_to_async
def _user_from_ticket(ticket):
    from apps.notifications.services.ws_ticket_service import (
        WebSocketTicketService,
    )
    from apps.users.models.user import User

    user_id = WebSocketTicketService().redeem(ticket)

    if user_id is None:
        return None

    return User.objects.filter(id=user_id, is_active=True).first()


def _query_param(scope, name):
    from urllib.parse import unquote

    query = (scope.get("query_string") or b"").decode(errors="ignore")

    for part in query.split("&"):
        key, _, value = part.partition("=")

        if key == name:
            return unquote(value)

    return ""


def _has_authorization(scope):
    return any(name == b"authorization" for name, _ in scope.get("headers", []))


def _token_from_scope(scope):
    for name, value in scope.get("headers", []):
        if name == b"authorization":
            scheme, _, token = value.decode("latin1").partition(" ")

            # A header that is present but not Bearer is a failed login, not
            # a reason to fall back to the query string.
            return token.strip() if scheme.lower() == "bearer" else ""

    query = (scope.get("query_string") or b"").decode(errors="ignore")

    for part in query.split("&"):
        key, _, value = part.partition("=")

        if key == "token":
            from urllib.parse import unquote

            return unquote(value)

    return ""


class NotificationConsumer(AsyncJsonWebsocketConsumer):

    async def connect(self):
        if not getattr(settings, "REALTIME_ENABLED", False):
            # Refused rather than accepted-and-silent: a client that connects
            # successfully and then never receives anything looks like a
            # backend that is broken, not one with the feature switched off.
            await self.close(code=4503)
            return

        ticket = _query_param(self.scope, "ticket")

        if ticket and not _has_authorization(self.scope):
            user = await _user_from_ticket(ticket)
        else:
            user = await _user_from_token(_token_from_scope(self.scope))

        if user is None:
            # 4401 rather than a plain close: the client has to be able to
            # tell "your token expired, refresh and reconnect" apart from
            # "the network dropped", or it will reconnect forever with the
            # same dead token.
            await self.close(code=4401)
            return

        self.user = user
        self.group = group_for(user.pk)

        await self.channel_layer.group_add(self.group, self.channel_name)
        await self.accept()

        # Sent so the client knows the socket is authenticated and live,
        # rather than merely open — the two are different, and only one of
        # them means notifications will arrive.
        await self.send_json({"type": "connected"})

    async def disconnect(self, code):
        group = getattr(self, "group", None)

        if group is not None:
            await self.channel_layer.group_discard(group, self.channel_name)

    async def receive_json(self, content, **kwargs):
        """Inbound is a keepalive and nothing else.

        Ignoring unknown messages rather than closing is deliberate: a proxy
        or a client library sending something unexpected should not drop a
        working connection.
        """
        if isinstance(content, dict) and content.get("type") == "ping":
            await self.send_json({"type": "pong"})

    async def notification_message(self, event):
        """Fan-out target — the ``notification.message`` type in realtime.py."""
        await self.send_json(
            {"type": "notification", "notification": event["payload"]}
        )
