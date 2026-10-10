from django.db.models import Q
from rest_framework.exceptions import ValidationError

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
        before=None,
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

        if before is not None:
            return self._after_cursor(
                user=user, queryset=queryset, before=before,
                page_size=page_size,
            )

        result = PaginationService.paginate(
            queryset=queryset,
            page=page,
            page_size=page_size,
        )

        result["next_cursor"] = self._next_cursor(
            result["items"], result["pagination"]["hasNext"]
        )

        return result

    def _after_cursor(self, *, user, queryset, before, page_size):
        """The rows older than ``before``, newest first (DASH-7).

        Offset paging on a feed that grows at the top shifts every page when
        a notification arrives, so rows repeat or go missing between pages. A
        cursor names the last row seen, and what comes after it does not move.
        """
        anchor = self.repository.get_by_id(user=user, notification_id=before)

        if anchor is None:
            raise ValidationError({"before": ["Notification not found."]})

        older = queryset.filter(
            Q(created_at__lt=anchor.created_at)
            | Q(created_at=anchor.created_at, id__lt=anchor.id)
        )

        # One extra row says whether there is a next page without a count.
        rows = list(older[: page_size + 1])
        has_next = len(rows) > page_size
        items = rows[:page_size]

        return {
            "items": items,
            "pagination": {"pageSize": page_size, "hasNext": has_next},
            "next_cursor": self._next_cursor(items, has_next),
        }

    @staticmethod
    def _next_cursor(items, has_next):
        return str(items[-1].id) if has_next and items else None

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