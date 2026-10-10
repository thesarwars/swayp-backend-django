"""Async OTP delivery (E2-S1).

Delivery runs off-request behind the MessagingProvider interface, so a slow or
failing mail server never blocks registration or login. The code itself is
already persisted by the time this runs — the task only delivers.
"""

import logging

from celery import shared_task

from integrations.factory import get_messaging_provider
from integrations.messaging.base import ChannelNotSupported, Message

logger = logging.getLogger(__name__)

#: Subject + body per purpose. Keyed by OTPPurpose value.
_TEMPLATES = {
    "REGISTRATION": (
        "Verify Your Swayp Account",
        "Hello,\n\nThis is your Swayp verification code:\n\n{code}\n\n"
        "It will expire in 5 minutes.\n\nThanks,\nSwayp Team\n",
    ),
    "LOGIN": (
        "Your Swayp Login OTP",
        "Hello,\n\nWe received a login request for your Swayp account.\n\n"
        "Your verification code is:\n\n{code}\n\n"
        "It will expire in 5 minutes.\n\nThanks,\nSwayp Team\n",
    ),
    "RESET_PASSWORD": (
        "Reset Your Swayp Password",
        "Hello,\n\nYou requested a password reset for your Swayp account.\n\n"
        "Your verification code is:\n\n{code}\n\n"
        "It will expire in 5 minutes.\n\nThanks,\nSwayp Team\n",
    ),
    "PHONE_CHANGE": (
        "Confirm Your New Swayp Phone Number",
        "Hello,\n\nYou asked to set a new phone number on your Swayp "
        "account.\n\nYour verification code is:\n\n{code}\n\n"
        "It will expire in 5 minutes. If this wasn't you, ignore this email "
        "and your number stays as it is.\n\nThanks,\nSwayp Team\n",
    ),
}

_FALLBACK = (
    "Swayp OTP",
    "Hello,\n\nYour Swayp code is:\n\n{code}\n\n"
    "It will expire in 5 minutes.\n\nThanks,\nSwayp Team\n",
)


def render(purpose, code):
    subject, body = _TEMPLATES.get(purpose, _FALLBACK)

    return subject, body.format(code=code)


@shared_task(name="authentication.send_otp", bind=True, max_retries=3)
def send_otp(self, *, destination, code, purpose, channel):
    """Deliver one OTP.

    Transient failures (mail server down) retry with backoff. An unsupported
    channel is permanent — retrying it would just burn the queue.
    """
    subject, body = render(purpose, code)

    try:
        result = get_messaging_provider().send(
            Message(
                to=destination,
                subject=subject,
                body=body,
                channel=channel,
            )
        )

        if not result.delivered:
            raise RuntimeError(
                f"OTP delivery reported failure: {result.detail or 'unknown'}"
            )

    except ChannelNotSupported:
        logger.error(
            "OTP delivery attempted on unsupported channel %s", channel
        )
        raise

    except Exception as exc:
        logger.warning("OTP delivery failed, retrying: %s", exc)
        raise self.retry(exc=exc, countdown=2 ** self.request.retries)

    logger.info("OTP delivered via %s for %s", channel, purpose)

    return result.provider_reference
