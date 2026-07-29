from django.db import transaction

from apps.notifications.channels import BY_FIELD, CHANNEL_LABELS
from apps.notifications.models import CHANNEL_FIELDS, NotificationPreference
from apps.notifications.selectors.preference_selector import (
    NotificationPreferenceSelector,
)


def channel_capabilities():
    """What the product can deliver on, derived from the channel registry.

    ``supported`` means an adapter class is registered; ``enabled`` means
    deliveries actually leave the box right now. They are different facts and
    the client needs both: email is supported but flagged off this release,
    SMS is neither.
    """
    capabilities = []

    for name in CHANNEL_FIELDS:
        key, label = CHANNEL_LABELS[name]
        channel = BY_FIELD.get(name)

        capabilities.append(
            {
                "key": key,
                "label": label,
                "supported": channel is not None,
                "enabled": bool(channel and channel.is_enabled()),
            }
        )

    return capabilities


class NotificationPreferenceService:

    def __init__(self):
        self.selector = NotificationPreferenceSelector()

    def get(self, *, user):
        return {
            "channels": channel_capabilities(),
            "preferences": self.selector.matrix(user=user),
        }

    @transaction.atomic
    def update(self, *, user, updates):
        """Upsert one row per named type. Only named channels change.

        update_or_create gives exactly the partial semantics the screen needs
        — an absent channel takes the column default on insert and is left
        alone on update — and it re-reads on an IntegrityError, so two
        concurrent PATCHes for the same (user, type) do not 500 against
        uniq_pref_per_type.
        """
        for update in updates:
            values = dict(update)
            notification_type = values.pop("type")

            NotificationPreference.objects.update_or_create(
                user=user,
                type=notification_type,
                defaults=values,
            )

        return self.get(user=user)
