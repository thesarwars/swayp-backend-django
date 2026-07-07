from apps.common.exceptions import NotFoundException
from apps.common.pagination import PaginationService

from .repositories import NotificationRepository


class NotificationService:

    def __init__(self):
        self.repository = NotificationRepository()

    def list_notifications(
        self,
        *,
        user,
        page=1,
        page_size=20,
    ):
        queryset = self.repository.list_by_user(user)

        return PaginationService.paginate(
            queryset=queryset,
            page=page,
            page_size=page_size,
        )

    def unread_count(
        self,
        *,
        user,
    ):
        return self.repository.unread_count(user)

    def mark_as_read(
        self,
        *,
        user,
        notification_id,
    ):
        notification = self.repository.get_by_id(
            user=user,
            notification_id=notification_id,
        )

        if notification is None:
            raise NotFoundException(
                "Notification not found."
            )

        if not notification.is_read:
            self.repository.mark_as_read(notification)

        return notification

    def mark_all_as_read(
        self,
        *,
        user,
    ):
        self.repository.mark_all_as_read(user)