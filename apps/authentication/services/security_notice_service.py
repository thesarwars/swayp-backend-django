"""Queue a security notice email (see tasks.send_security_notice)."""

import logging

from django.db import transaction

logger = logging.getLogger(__name__)


def notify(user, kind):
    """Email ``user`` that their account's protection changed.

    After commit, so a rolled-back change sends nothing, and never allowed to
    fail the request: the change already happened, and the email is a
    courtesy about it. A broker that is down falls back to sending inline.
    """

    def send():
        from apps.authentication.tasks import send_security_notice

        payload = {"destination": user.email, "kind": kind}

        try:
            send_security_notice.delay(**payload)
            return
        except Exception as exc:
            logger.error(
                "security notice could not be queued (%s: %s) — sending inline",
                type(exc).__name__,
                exc,
            )

        try:
            send_security_notice(**payload)
        except Exception:
            logger.exception("security notice %s failed for %s", kind, user.pk)

    transaction.on_commit(send)
