"""Deterministic messaging provider for dev and tests — logs, never sends."""

import logging

from integrations.messaging.base import (
    ChannelNotSupported,
    DeliveryResult,
    Message,
    MessagingProvider,
)

logger = logging.getLogger(__name__)


class MockMessagingProvider(MessagingProvider):

    name = "mock"
    supported_channels = ("EMAIL",)

    def send(self, message: Message) -> DeliveryResult:
        if not self.supports(message.channel):
            raise ChannelNotSupported(
                f"No delivery adapter for channel '{message.channel}'."
            )

        logger.info(
            "[mock-messaging] %s -> %s | %s",
            message.channel,
            message.to,
            message.subject,
        )

        return DeliveryResult(
            delivered=True,
            provider_reference=f"MOCK-MSG-{message.channel}",
        )
