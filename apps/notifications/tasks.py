"""Async notification delivery (E8-S3).

Deliberately unlike apps/authentication/tasks.py, which retries: an OTP blocks
a user mid-flow, a notification email does not, and the in-app row already
carries the message. Retrying would also land in the caller's stack under the
test settings, which pin CELERY_TASK_ALWAYS_EAGER and
CELERY_TASK_EAGER_PROPAGATES.
"""

import logging

from celery import shared_task
from django.conf import settings

from integrations.factory import get_messaging_provider
from integrations.messaging.base import ChannelNotSupported, Message

logger = logging.getLogger(__name__)


@shared_task(name="notifications.send_notification_email")
def send_notification_email(*, to, subject, body, notification_type=""):
    """Deliver one notification email. Never raises.

    The status strings mirror the channel outcome vocabulary in
    apps/notifications/channels/base.py but are written out rather than
    imported from it: Celery's autodiscovery imports this module first, and
    that package imports this one.
    """
    # Re-checked here as well as in EmailChannel.is_enabled: a task already on
    # the queue when the flag is turned off must not send.
    if not settings.NOTIFICATION_EMAIL_ENABLED:
        return "disabled"

    try:
        result = get_messaging_provider().send(
            Message(to=to, subject=subject, body=body, channel="EMAIL")
        )
    except ChannelNotSupported:
        logger.error("notification email: provider has no EMAIL adapter")
        return "unsupported"
    except Exception:
        logger.exception("notification email failed for %s", notification_type)
        return "failed"

    return "sent" if result.delivered else "failed"
