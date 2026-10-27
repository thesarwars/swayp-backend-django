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


# --- security notices -----------------------------------------------------
# Sent when something changes how the account is protected, so a change the
# owner did not make is noticed. Each ends with what to do if it wasn't them.

_NOT_YOU = (
    "If this wasn't you, reset your password now and contact Swayp support."
)

_NOTICES = {
    "MFA_ENABLED": (
        "Two-step verification is on",
        "Hello,\n\nTwo-step verification was turned on for your Swayp "
        "account. Signing in now also needs a code from your authenticator "
        "app.\n\n" + _NOT_YOU + "\n\nThanks,\nSwayp Team\n",
    ),
    "MFA_DISABLED": (
        "Two-step verification is off",
        "Hello,\n\nTwo-step verification was turned off for your Swayp "
        "account, and every other device was signed out.\n\n" + _NOT_YOU
        + "\n\nThanks,\nSwayp Team\n",
    ),
    "MFA_RECOVERY_CODE_USED": (
        "A recovery code was used to sign in",
        "Hello,\n\nSomeone signed in to your Swayp account with one of your "
        "recovery codes. Each code works once; you can make a new set in "
        "Settings > Security.\n\n" + _NOT_YOU + "\n\nThanks,\nSwayp Team\n",
    ),
    "PASSWORD_CHANGED": (
        "Your Swayp password was changed",
        "Hello,\n\nThe password for your Swayp account was just changed, and "
        "every other device was signed out.\n\n" + _NOT_YOU
        + "\n\nThanks,\nSwayp Team\n",
    ),
}


@shared_task(name="authentication.send_security_notice", bind=True, max_retries=3)
def send_security_notice(self, *, destination, kind):
    subject, body = _NOTICES[kind]

    try:
        result = get_messaging_provider().send(
            Message(to=destination, subject=subject, body=body, channel="EMAIL")
        )

        if not result.delivered:
            raise RuntimeError(
                f"Notice delivery reported failure: {result.detail or 'unknown'}"
            )

    except ChannelNotSupported:
        logger.error("security notice attempted on an unsupported channel")

        return None

    except Exception as exc:
        logger.warning("security notice %s failed, retrying: %s", kind, exc)
        raise self.retry(exc=exc, countdown=2 ** self.request.retries)

    return result.provider_reference
