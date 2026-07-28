"""Messaging provider interface (E2-S1).

Email only this release (BRD §1.2). The SMS branch exists so the OTP screens
can be built against a real vocabulary, but no SMS adapter is wired — calling
it raises rather than silently dropping a message.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass


class ChannelNotSupported(Exception):
    """Raised when a channel has no delivery adapter in this release."""


@dataclass(frozen=True)
class Message:
    to: str
    subject: str
    body: str
    channel: str


@dataclass(frozen=True)
class DeliveryResult:
    delivered: bool
    provider_reference: str = ""
    detail: str = ""


class MessagingProvider(ABC):
    name = "base"

    #: Channels this provider can actually deliver on.
    supported_channels: tuple[str, ...] = ()

    def supports(self, channel: str) -> bool:
        return channel in self.supported_channels

    @abstractmethod
    def send(self, message: Message) -> DeliveryResult:
        ...
