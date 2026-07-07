from django.contrib.auth import get_user_model

from apps.notifications.repositories import (
    NotificationRepository,
)

User = get_user_model()


class DashboardRepository:

    def __init__(self):
        self.notification_repository = (
            NotificationRepository()
        )

    def get_user(self, user_id):
        return (
            User.objects
            .select_related("wallet")
            .filter(id=user_id)
            .first()
        )

    def get_unread_notification_count(
        self,
        user,
    ):
        return self.notification_repository.unread_count(
            user
        )