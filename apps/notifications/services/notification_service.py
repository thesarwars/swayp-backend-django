from apps.common.exceptions import NotFoundException

from apps.notifications.repositories import NotificationRepository
from apps.notifications.selectors.notification_selector import (
    NotificationSelector,
)


class NotificationService:

    def __init__(self):
        self.repository = NotificationRepository()
        self.selector = NotificationSelector()

    def list_notifications(
        self,
        *,
        user,
        page=1,
        page_size=20,
        types=None,
        category=None,
        is_read=None,
        before=None,
    ):
        return self.selector.list_notifications(
            user=user,
            page=page,
            page_size=page_size,
            types=types,
            category=category,
            is_read=is_read,
            before=before,
        )

    def unread_count(
        self,
        *,
        user,
    ):
        return self.selector.unread_count(
            user=user,
        )

    def mark_as_read(
        self,
        *,
        user,
        notification_id,
    ):
        notification = self.selector.get_notification(
            user=user,
            notification_id=notification_id,
        )

        if notification is None:
            raise NotFoundException(
                "Notification not found."
            )

        if not notification.is_read:
            self.repository.mark_as_read(
                notification,
            )

        return notification

    def mark_all_as_read(
        self,
        *,
        user,
    ):
        """How many were unread and are now read; 0 when there were none."""
        return self.repository.mark_all_as_read(user)