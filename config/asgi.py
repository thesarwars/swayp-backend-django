"""ASGI entrypoint — HTTP and WebSocket (E8-S5).

Both protocols are served by one application so a single process can carry
them. HTTP behaviour is unchanged; the websocket branch only exists when
channels is installed, so a WSGI-only deployment continues to run the whole
product without the dependency.

The Django application is built FIRST, before anything imports a consumer.
Consumers import models, and importing a model before the app registry is
populated raises AppRegistryNotReady — a failure that appears only under the
ASGI server and not under runserver, which is the worst kind to debug.
"""

import os

from django.core.asgi import get_asgi_application

os.environ.setdefault(
    "DJANGO_SETTINGS_MODULE",
    "config.settings.local",
)

django_application = get_asgi_application()


def websocket_origins():
    """Origins allowed to open a socket — the frontend's, not our own.

    channels ships AllowedHostsOriginValidator, and using it here is wrong in
    a way that only appears in production. It validates the browser's Origin
    header against ALLOWED_HOSTS — but ALLOWED_HOSTS names the hosts this API
    answers to (api.getswayp.com), while the Origin is the *frontend*
    (app.getswayp.com). With separate domains, which is this deployment, every
    real browser connection is refused; in development, where the two are the
    same host, it works perfectly. That combination is the hardest kind of bug
    to find, so the list is taken from somewhere that is already correct.

    CORS_ALLOWED_ORIGINS is exactly "the origins allowed to call this API", so
    the socket reads the same list. Nothing new to configure, and the HTTP and
    WebSocket policies cannot drift apart.
    """
    from django.conf import settings

    if getattr(settings, "CORS_ALLOW_ALL_ORIGINS", False):
        # Development only — production.py replaces this with an explicit
        # allow-list and refuses to boot without one.
        return ["*"]

    origins = list(getattr(settings, "CORS_ALLOWED_ORIGINS", []) or [])

    if origins:
        return origins

    # No CORS list at all: fall back to the hosts we answer to, which is
    # correct for a same-origin deployment and is what channels would have
    # done anyway.
    hosts = list(getattr(settings, "ALLOWED_HOSTS", []) or [])

    if getattr(settings, "DEBUG", False) and not hosts:
        return ["localhost", "127.0.0.1", "[::1]"]

    return hosts


try:
    from channels.routing import ProtocolTypeRouter, URLRouter
    from channels.security.websocket import OriginValidator

    from apps.notifications.routing import websocket_urlpatterns

    application = ProtocolTypeRouter(
        {
            "http": django_application,
            # A WebSocket is not subject to the same-origin policy the way
            # fetch() is, so without this any site a signed-in user visits
            # could open a socket to this host. Authentication still happens
            # in the consumer; this closes the door before a token is read.
            "websocket": OriginValidator(
                URLRouter(websocket_urlpatterns),
                websocket_origins(),
            ),
        }
    )
except ImportError:
    # channels not installed — serve HTTP exactly as before.
    application = django_application
