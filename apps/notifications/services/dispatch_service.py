"""notify() — the one way an event becomes a notification (E8-S3).

Lives in the notifications package rather than apps/common because it owns
model writes, preference reads and user-facing copy.

The split between what raises and what does not is the whole contract. A
developer error — unknown type, missing template context, an override for a
templated type — raises, because the alternative is a half-formatted sentence
in front of a user. A delivery failure never raises into the caller, because
the caller is usually settling money and SMTP being down is not a reason to
roll a payment back. The in-app write is deliberately not shielded: it is the
durable record, and it already ran inside the caller's transaction at every
call-site this replaces.
"""

from dataclasses import dataclass

from apps.notifications.channels import (
    BY_FIELD,
    CHANNELS,
    DISABLED,
    FIELD_TO_KEY,
    SKIPPED_BY_PREFERENCE,
    UNSUPPORTED,
    Dispatch,
)
from apps.notifications.models import CHANNEL_FIELDS, Notification
from apps.notifications.selectors.preference_selector import (
    NotificationPreferenceSelector,
)
from apps.notifications.services.notification_templates import render


@dataclass(frozen=True)
class NotifyResult:
    notification: object | None
    outcomes: dict


def dedupe_key_is_storable():
    """Whether a dedupe_key can actually be persisted yet.

    ``Notification.dedupe_key`` lands with the reminder job (E8-S4); the
    parameter ships now so S4's call shape compiles against S3. Asked of the
    model rather than hard-coded, so the guard below disarms itself the moment
    the column exists instead of having to be found and deleted.
    """
    return any(
        field.name == "dedupe_key" for field in Notification._meta.get_fields()
    )


class NotificationDispatchService:

    def __init__(self):
        self.preferences = NotificationPreferenceSelector()
        # One instance, one snapshot of the preferences it has already read.
        # The free ``notify()`` below builds a fresh service per call, so every
        # event-driven caller reads through exactly as it did before and a
        # PATCH to preferences can never be served stale. The memo only pays
        # off for a batch producer that holds one instance for the length of
        # its run — E8-S4's nightly sweep, where a user with twenty bills
        # otherwise costs twenty byte-identical SELECTs for the same row.
        self._resolved = {}

    def _resolve(self, *, user, type):
        cache_key = (user.pk, str(type))

        if cache_key not in self._resolved:
            self._resolved[cache_key] = self.preferences.resolve(
                user=user, type=type
            )

        return self._resolved[cache_key]

    def notify(
        self,
        *,
        user,
        type,
        context=None,
        title=None,
        message=None,
        dedupe_key=None,
    ):
        # Checked here, before preferences are even read, and not inside
        # InAppChannel: that channel is skipped entirely when the user has
        # in_app switched off for this type, so a key handed to it would
        # vanish without a sound for exactly those users while the email still
        # went out. An idempotency guarantee that holds for some users and not
        # others is worse than none at all, so the refusal cannot be allowed
        # to depend on a preference.
        if dedupe_key is not None and not dedupe_key_is_storable():
            raise TypeError(
                f"notify() was given dedupe_key={dedupe_key!r}, but "
                "Notification.dedupe_key does not exist yet (E8-S4 adds it). "
                "Refusing rather than dropping it."
            )

        context = context or {}
        title, message = render(
            type, context, title=title, message=message
        )

        resolved = self._resolve(user=user, type=type)

        dispatch = Dispatch(
            user=user,
            type=str(type),
            title=title,
            message=message,
            context=context,
            dedupe_key=dedupe_key,
        )

        outcomes = {}

        for channel in CHANNELS:
            if not resolved[channel.preference_field]:
                outcomes[channel.key] = SKIPPED_BY_PREFERENCE
                continue

            if not channel.is_enabled():
                outcomes[channel.key] = DISABLED
                continue

            outcomes[channel.key] = channel.deliver(dispatch)

        # Channels the user has a column for but the product has no adapter
        # for are reported, never attempted.
        for name in CHANNEL_FIELDS:
            if name not in BY_FIELD:
                outcomes[FIELD_TO_KEY[name]] = UNSUPPORTED

        return NotifyResult(
            notification=dispatch.notification,
            outcomes=outcomes,
        )


def notify(
    user,
    type,
    context=None,
    *,
    title=None,
    message=None,
    dedupe_key=None,
):
    return NotificationDispatchService().notify(
        user=user,
        type=type,
        context=context,
        title=title,
        message=message,
        dedupe_key=dedupe_key,
    )
