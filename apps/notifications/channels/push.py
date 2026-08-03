"""Push delivery (E8-S5).

Fills the PUSH slot the channel vocabulary has reserved since E8-S3. Until now
there was no class here on purpose — a channel with no adapter is unreachable
code rather than a boolean someone can flip — so registering this class is the
whole act of turning push on.

Modelled on EmailChannel, including the on_commit hand-off: a worker must not
be able to read a notification row before the transaction that wrote it has
committed, and a caller settling a payment must never be rolled back because
Firebase was slow.
"""

import functools
import logging

from django.conf import settings
from django.db import transaction

from apps.notifications.channels.base import (
    PENDING_COMMIT,
    PUSH,
    NotificationChannel,
)
from apps.notifications.tasks import send_push

logger = logging.getLogger(__name__)


class PushChannel(NotificationChannel):

    key = PUSH
    preference_field = "push"

    def is_enabled(self):
        return bool(getattr(settings, "PUSH_ENABLED", False))

    def deliver(self, dispatch):
        # Tokens are deliberately not read here. Resolving them at send time
        # in the worker means a device registered or signed out between this
        # call and delivery is respected — and it keeps a database query off
        # the payment path.
        transaction.on_commit(
            functools.partial(
                self._queue,
                user_id=dispatch.user.pk,
                title=dispatch.title,
                body=dispatch.message,
                data=self._payload(dispatch),
                notification_type=dispatch.type,
            )
        )

        # PENDING_COMMIT for the same reason as email: nothing has reached the
        # broker yet, and the caller's transaction may still roll back and take
        # this callback with it. Claiming "sent" here would be a claim this
        # method is in no position to make.
        return PENDING_COMMIT

    @staticmethod
    def _payload(dispatch):
        """What the client needs to route the tap, and nothing more.

        Deliberately not the whole context: a push payload travels through
        Apple's and Google's infrastructure and is visible to the OS, so it
        carries identifiers rather than amounts or vendor names. The client
        fetches the notification over the authenticated API to display it.
        """
        payload = {"type": dispatch.type}

        notification = getattr(dispatch, "notification", None)

        if notification is not None and getattr(notification, "pk", None):
            payload["notificationId"] = str(notification.pk)

        for key in ("billId", "paymentId", "occurrenceId", "vendorId"):
            if key in (dispatch.context or {}):
                payload[key] = str(dispatch.context[key])

        return payload

    @staticmethod
    def _queue(*, user_id, title, body, data, notification_type):
        try:
            send_push.delay(
                user_id=str(user_id),
                title=title,
                body=body,
                data=data,
                notification_type=notification_type,
            )
        except Exception:
            # An on_commit callback raises in the committing thread, after the
            # caller's transaction is already durable — a dead broker must not
            # surface as a failed payment.
            logger.exception("notify: could not queue push notification")
