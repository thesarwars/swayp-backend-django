from .base import (
    CHANNEL_LABELS,
    DISABLED,
    EMAIL,
    FAILED,
    FIELD_TO_KEY,
    IN_APP,
    PENDING_COMMIT,
    PUSH,
    SENT,
    SKIPPED_BY_PREFERENCE,
    SMS,
    UNSUPPORTED,
    Dispatch,
    NotificationChannel,
)
from .email import EmailChannel
from .in_app import InAppChannel

#: InAppChannel FIRST, and the order is load-bearing rather than stylistic:
#: the in-app write is the durable record and, from E8-S4, the row that claims
#: the dedupe key — so it has to resolve before any external channel is
#: dispatched, or an email goes out for an event a unique-key collision was
#: about to reject.
CHANNELS = (InAppChannel(), EmailChannel())

SUPPORTED_KEYS = {channel.key for channel in CHANNELS}

#: Preference column -> channel, for the ones that have an adapter. SMS and
#: push are absent by construction: there is no class to register.
BY_FIELD = {channel.preference_field: channel for channel in CHANNELS}

__all__ = [
    "BY_FIELD",
    "CHANNELS",
    "CHANNEL_LABELS",
    "DISABLED",
    "EMAIL",
    "FAILED",
    "FIELD_TO_KEY",
    "IN_APP",
    "PENDING_COMMIT",
    "PUSH",
    "SENT",
    "SKIPPED_BY_PREFERENCE",
    "SMS",
    "SUPPORTED_KEYS",
    "UNSUPPORTED",
    "Dispatch",
    "EmailChannel",
    "InAppChannel",
    "NotificationChannel",
]
