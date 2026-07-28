"""Django-backed email delivery (E2-S1).

Uses whatever EMAIL_BACKEND is configured, so switching to Postmark or SES at
R4 is a settings change rather than a code change.
"""

import logging

from django.conf import settings
from django.core.mail import send_mail

from integrations.messaging.base import (
    ChannelNotSupported,
    DeliveryResult,
    Message,
    MessagingProvider,
)

logger = logging.getLogger(__name__)


class DjangoEmailMessagingProvider(MessagingProvider):

    name = "django_email"
    supported_channels = ("EMAIL",)

    def send(self, message: Message) -> DeliveryResult:
        if not self.supports(message.channel):
            raise ChannelNotSupported(
                f"No delivery adapter for channel '{message.channel}'."
            )

        sent = send_mail(
            subject=message.subject,
            message=message.body,
            from_email=(
                settings.DEFAULT_FROM_EMAIL or settings.EMAIL_HOST_USER
            ),
            recipient_list=[message.to],
            fail_silently=False,
        )

        return DeliveryResult(
            delivered=bool(sent),
            provider_reference="",
            detail="" if sent else "Email backend reported 0 sent.",
        )
