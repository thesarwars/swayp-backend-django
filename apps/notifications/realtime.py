"""Live notification fan-out (E8-S5).

The socket is a *transport for the in-app channel*, not a channel of its own.
That distinction decides the whole design:

* There is no ``websocket`` preference column, and there should not be. A user
  who has switched in-app notifications off for a type has no row written for
  it, so there is nothing to broadcast — the preference is already respected,
  once, in the place that owns it.
* The broadcast carries the row that was just written. The socket and a later
  ``GET /notifications/`` therefore cannot disagree, because they are showing
  the same record rather than two independently-built payloads.

Everything here is best-effort and silent on failure. A browser missing a live
update is a cosmetic problem it fixes itself on the next fetch; a payment
rolled back because Redis was briefly unreachable is not.
"""

import logging

from django.conf import settings

logger = logging.getLogger(__name__)

#: One group per user. Named from the primary key rather than anything
#: user-controlled: group names reach Redis, and a channel layer rejects
#: characters that a display name would happily contain.
GROUP_TEMPLATE = "notify.user.{}"


def group_for(user_id):
    return GROUP_TEMPLATE.format(user_id)


def broadcast(*, user_id, payload):
    """Push one event to every socket this user has open. Never raises.

    Called from an on_commit hook, so it runs after the caller's transaction
    is durable — a browser must never be told about a row that is about to be
    rolled back.
    """
    if not getattr(settings, "REALTIME_ENABLED", False):
        return False

    try:
        from asgiref.sync import async_to_sync
        from channels.layers import get_channel_layer
    except ImportError:
        # channels is an optional dependency: a WSGI-only deployment runs the
        # whole product without it, and must not crash for lacking it.
        logger.debug("realtime: channels is not installed")
        return False

    try:
        layer = get_channel_layer()

        if layer is None:
            logger.warning("realtime: REALTIME_ENABLED but no channel layer")
            return False

        async_to_sync(layer.group_send)(
            group_for(user_id),
            {"type": "notification.message", "payload": payload},
        )
    except Exception:
        # Redis down, layer misconfigured, event loop already closed — none of
        # these is a reason to fail the caller. The durable row is already
        # written and the client will see it on its next fetch.
        logger.exception("realtime: broadcast failed")
        return False

    return True
