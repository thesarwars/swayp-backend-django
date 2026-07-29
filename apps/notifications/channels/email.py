import functools
import logging

from django.conf import settings
from django.db import transaction

from apps.notifications.channels.base import (
    EMAIL,
    FAILED,
    PENDING_COMMIT,
    NotificationChannel,
)
from apps.notifications.tasks import send_notification_email

logger = logging.getLogger(__name__)


class EmailChannel(NotificationChannel):

    key = EMAIL
    preference_field = "email"

    def is_enabled(self):
        return bool(getattr(settings, "NOTIFICATION_EMAIL_ENABLED", False))

    def deliver(self, dispatch):
        recipient = getattr(dispatch.user, "email", "")

        if not recipient:
            logger.warning("notify: user %s has no email", dispatch.user.pk)
            return FAILED

        # on_commit so the worker cannot race the in-app row it links to,
        # same reasoning as the OTP delivery path.
        transaction.on_commit(
            functools.partial(
                self._queue,
                recipient=recipient,
                subject=dispatch.title,
                body=dispatch.message,
                notification_type=dispatch.type,
            )
        )

        # PENDING_COMMIT, not QUEUED: nothing has been handed to the broker
        # yet and the caller's transaction may still roll back, taking this
        # callback with it. Reporting "queued" here would be a claim this
        # method is in no position to make — the enqueue happens strictly
        # after it returns, so a broker failure is only visible in the log.
        return PENDING_COMMIT

    @staticmethod
    def _queue(*, recipient, subject, body, notification_type):
        try:
            send_notification_email.delay(
                to=recipient,
                subject=subject,
                body=body,
                notification_type=notification_type,
            )
        except Exception:
            # An on_commit callback raises in the committing thread, after
            # the caller's transaction is already durable — a dead broker
            # must not surface as a failed payment.
            logger.exception("notify: could not queue notification email")
