"""Push notification provider interface (E8-S5).

One interface for every platform. Firebase Cloud Messaging fans out to APNs
for iOS, to Android directly, and to the browser Push API for web — so the
application never learns which platform a token belongs to in order to send
to it. ``DeviceToken.platform`` is recorded for support and analytics, never
branched on here.

Two things this interface deliberately makes explicit.

**Dead tokens are a return value, not an exception.** A token dies whenever an
app is uninstalled, a browser subscription is revoked, or FCM rotates it, and
the provider is the only party that learns this. If that arrived as a generic
failure the row would be retried forever and every send would get slower as
the dead ones accumulated. ``rejected_tokens`` names them so the caller can
deactivate exactly those rows and nothing else.

**A partial send is the normal case.** One user has several devices. A phone
that has been wiped must not stop the send to their laptop, so the result
reports sent and rejected side by side rather than a single boolean.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field


@dataclass(frozen=True)
class PushMessage:
    """One notification, addressed to every device a user has registered."""

    tokens: tuple[str, ...]
    title: str
    body: str
    #: Delivered alongside the notification so the client can deep-link
    #: without a follow-up request. Values must be strings — FCM rejects a
    #: data payload with non-string values, and finding that out in
    #: production is worse than coercing here.
    data: dict = field(default_factory=dict)


@dataclass(frozen=True)
class PushResult:
    sent: int = 0
    failed: int = 0
    #: Tokens the provider says will never be deliverable again. The caller
    #: deactivates these; anything else is treated as transient.
    rejected_tokens: tuple[str, ...] = ()
    detail: str = ""


class PushProvider(ABC):
    name = "base"

    def is_configured(self) -> bool:
        """Whether this provider can actually reach a device right now.

        Separate from selection: a deployment can have PUSH_PROVIDER=fcm with
        no credentials yet, and that must degrade to "not delivered" rather
        than raise into a caller that is settling a payment.
        """
        return True

    @abstractmethod
    def send(self, message: PushMessage) -> PushResult:
        """Deliver to every token. Must not raise."""
