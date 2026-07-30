"""Async team-invite delivery (E10-S2).

Reuses the E2 messaging provider, so invitations go out the same way OTPs do
and CI stays free of a real mail server. The invitation row is already
committed by the time this runs — the task only delivers, which is why a
failure here is logged rather than raised: the seat is taken and the link can
be resent.
"""

import logging

from celery import shared_task
from django.conf import settings

from integrations.factory import get_messaging_provider
from integrations.messaging.base import ChannelNotSupported, Message

logger = logging.getLogger(__name__)

SUBJECT = "You've been invited to Swayp"

BODY = (
    "Hello,\n\n"
    "{account_name} has invited you to join their Swayp account as "
    "{role_label}.\n\n"
    "Accept the invitation here:\n\n{link}\n\n"
    "This invitation expires in 14 days.\n\n"
    "If you weren't expecting this, you can ignore this email.\n\n"
    "Thanks,\nSwayp Team\n"
)


def invite_link(token):
    """The URL the invitee opens.

    Built from a setting rather than hardcoded, because the accept page is a
    frontend route and the backend does not own its host.
    """
    base = getattr(settings, "FRONTEND_URL", "").rstrip("/")

    return f"{base}/teams/accept?token={token}"


def render(*, account_name, role, token):
    return SUBJECT, BODY.format(
        account_name=account_name,
        role_label=role.lower(),
        link=invite_link(token),
    )


@shared_task(name="teams.send_team_invite", bind=True, max_retries=3)
def send_team_invite(self, *, email, token, account_name, role):
    subject, body = render(
        account_name=account_name, role=role, token=token
    )

    try:
        result = get_messaging_provider().send(
            Message(
                to=email,
                subject=subject,
                body=body,
                channel="EMAIL",
            )
        )

        if not result.delivered:
            raise RuntimeError(
                f"Invite delivery reported failure: "
                f"{result.detail or 'unknown'}"
            )

    except ChannelNotSupported:
        # Permanent — retrying would only burn the queue.
        logger.error("invite delivery attempted on an unsupported channel")

        return None

    except Exception as exc:
        logger.warning(
            "invite delivery failed for %s (%s); retrying",
            email,
            exc,
        )

        raise self.retry(exc=exc, countdown=30)

    return True
