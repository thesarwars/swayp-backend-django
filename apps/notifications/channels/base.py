"""Notification delivery interface (E8-S3).

Modelled on integrations/messaging/base.py: a channel with no adapter has no
class here at all, so an attempt to deliver on it is unreachable code rather
than a branch someone can re-enable by flipping a boolean.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field

IN_APP = "IN_APP"
EMAIL = "EMAIL"
SMS = "SMS"
PUSH = "PUSH"

#: Preference column -> channel key, for every channel the model reserves a
#: column for — including the ones with no adapter, which is how notify()
#: reports them as unsupported instead of leaving them out of the result.
FIELD_TO_KEY = {
    "in_app": IN_APP,
    "email": EMAIL,
    "sms": SMS,
    "push": PUSH,
}

#: Preference column -> (API key, human label). The wire spells channels in
#: camelCase and the columns in snake_case; both come from here.
CHANNEL_LABELS = {
    "in_app": ("inApp", "In-app"),
    "email": ("email", "Email"),
    "sms": ("sms", "SMS"),
    "push": ("push", "Push"),
}

#: Outcomes reported per channel. Nothing else may be returned.
SENT = "sent"
#: Accepted for hand-off, and it will happen once the caller's transaction
#: commits — not "the broker took it". A channel that defers with
#: transaction.on_commit returns before the commit, so whether the enqueue
#: succeeded is genuinely unknowable at that point; the failure surfaces in
#: the log (and, once the NotificationDispatch ledger lands, there). Nothing
#: may read this as proof that anything left the box.
PENDING_COMMIT = "pending_commit"
SKIPPED_BY_PREFERENCE = "skipped_by_preference"
UNSUPPORTED = "unsupported"
DISABLED = "disabled"
#: Attempted and provably did not go out, decided before deliver() returned.
FAILED = "failed"


@dataclass
class Dispatch:
    """One event on its way out, shared by every channel in a single notify().

    Not frozen: InAppChannel writes the durable row and records it here, so
    later channels — and the caller, through NotifyResult — can reach it.
    """

    user: object
    type: str
    title: str
    message: str
    context: dict = field(default_factory=dict)
    dedupe_key: str | None = None
    notification: object | None = None


class NotificationChannel(ABC):

    key: str = ""
    preference_field: str = ""

    def is_enabled(self) -> bool:
        """Whether deliveries actually leave the box right now."""
        return True

    @abstractmethod
    def deliver(self, dispatch: Dispatch) -> str:
        """Return one of the outcome constants. Must not raise."""
