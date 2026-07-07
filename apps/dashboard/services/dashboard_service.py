from django.utils import timezone

from apps.common.exceptions import (
    NotFoundException,
)
from apps.dashboard.selectors.dashboard_selector import (
    DashboardSelector,
)


class DashboardService:

    def __init__(self):
        self.selector = DashboardSelector()

    def get_profile_summary(
        self,
        *,
        user,
    ):
        user = self.selector.get_user(
            user.id,
        )

        if user is None:
            raise NotFoundException(
                "User not found."
            )

        return {
            "id": user.id,
            "full_name": user.get_full_name(),
            "profile_picture": getattr(
                user,
                "profile_picture",
                None,
            ),
            "greeting": self._get_greeting(),
            "unread_notification_count": (
                self.selector.get_unread_notification_count(
                    user
                )
            ),
        }

    @staticmethod
    def _get_greeting():
        hour = timezone.localtime().hour

        if 5 <= hour < 12:
            return "Good Morning"

        if 12 <= hour < 17:
            return "Good Afternoon"

        if 17 <= hour < 21:
            return "Good Evening"

        return "Good Night"