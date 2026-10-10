from apps.common.enums import NOTIFICATION_CATEGORY_TYPES
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
        types=None,
        category=None,
        is_read=None,
    ):
        queryset = self.repository.list_by_user(user)

        # Filtered before paginating, so an empty page means "none match"
        # rather than "the matches are on a later page".
        if types:
            queryset = queryset.filter(type__in=types)

        if category:
            queryset = queryset.filter(
                type__in=NOTIFICATION_CATEGORY_TYPES[category],
            )

        if is_read is not None:
            queryset = queryset.filter(is_read=is_read)

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