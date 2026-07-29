from apps.common.enums import NotificationType
from apps.notifications.models import CHANNEL_FIELDS, NotificationPreference
from apps.notifications.repositories import NotificationPreferenceRepository


class NotificationPreferenceSelector:

    def __init__(self):
        self.repository = NotificationPreferenceRepository()

    @staticmethod
    def defaults():
        """Read off the model, so the API defaults, notify()'s fallback and
        the column defaults cannot drift apart."""
        return {
            name: NotificationPreference._meta.get_field(name).default
            for name in CHANNEL_FIELDS
        }

    def resolve(self, *, user, type):
        """Effective channels for one type. Never writes."""
        row = self.repository.get(user=user, type=str(type))

        if row is None:
            return self.defaults()

        return {name: getattr(row, name) for name in CHANNEL_FIELDS}

    def matrix(self, *, user):
        """Every notification type, stored value or default, in one query."""
        stored = {
            row.type: row
            for row in self.repository.list_by_user(user)
        }

        defaults = self.defaults()

        return [
            {
                "type": value,
                "label": label,
                "is_default": value not in stored,
                **(
                    {
                        name: getattr(stored[value], name)
                        for name in CHANNEL_FIELDS
                    }
                    if value in stored
                    else defaults
                ),
            }
            for value, label in NotificationType.choices
        ]
