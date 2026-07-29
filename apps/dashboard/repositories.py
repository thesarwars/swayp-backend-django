from django.contrib.auth import get_user_model

# The notifications *selector*, not its repository: one app's persistence layer
# is not another app's read surface, and E8-S3 restructures that module.
from apps.notifications.selectors.notification_selector import (
    NotificationSelector,
)

User = get_user_model()


class DashboardRepository:

    def __init__(self):
        self.notification_selector = (
            NotificationSelector()
        )

    def get_user(self, user_id):
        return (
            User.objects
            .filter(id=user_id)
            .first()
        )

    def get_unread_notification_count(
        self,
        user,
    ):
        return self.notification_selector.unread_count(
            user=user
        )
