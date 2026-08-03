"""WebSocket URL map (E8-S5).

Kept separate from api/urls/ because these are not HTTP routes: they are
reached through the ASGI application in config/asgi.py, and a path added to
the REST urlconf by mistake would 404 rather than fail loudly.
"""

from django.urls import path

from apps.notifications.consumers import NotificationConsumer

websocket_urlpatterns = [
    path("ws/notifications/", NotificationConsumer.as_asgi()),
]
