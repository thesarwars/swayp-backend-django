"""Notification background work (E8-S3 delivery, E8-S4 the daily sweep).

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


@shared_task(name="notifications.bill_status_notifier")
def bill_status_notifier():
    """Daily BILL_DUE + LATE_FEE_WARNING sweep (E8-S4).

    Safe to re-run on the same Eastern day: every emission is keyed and the key
    is unique in the database, so a replay after a crash resumes rather than
    repeats.
    """
    # Lazy, like apps/payments/tasks.py: Celery autodiscovery imports this
    # module while the app registry is still being populated.
    from apps.notifications.services import BillStatusNotifierService

    report = BillStatusNotifierService().run()

    logger.info(
        "bill_status_notifier bill_due=%s late_fee=%s live=%s dup=%s "
        "no_channel=%s failed=%s",
        report["bill_due"],
        report["late_fee"],
        report["skipped_live_payment"],
        report["skipped_duplicate"],
        report["skipped_no_channel"],
        report["failed"],
    )

    # bill_due + late_fee is a *send* count: an emission every channel was off
    # for lands in skipped_no_channel and is deliberately not in this number.
    return report["bill_due"] + report["late_fee"]
