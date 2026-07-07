from apps.common.pagination import PaginationService

from apps.notifications.repositories import NotificationRepository


class NotificationSelector:

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

    def get_notification(
        self,
        *,
        user,
        notification_id,
    ):
        return self.repository.get_by_id(
            user=user,
            notification_id=notification_id,
        )