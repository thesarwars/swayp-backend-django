from apps.common.dates import now_eastern
from apps.common.exceptions import (
    NotFoundException,
)
from apps.dashboard.selectors.dashboard_selector import (
    DashboardSelector,
)


from apps.users.services.display_name import display_name


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
            "full_name": display_name(user),
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
    def _get_greeting(now=None):
        # timezone.localtime() follows TIME_ZONE, which is UTC, so a US user
        # was greeted 4-5 hours ahead of their own clock — 8 AM ET read "Good
        # Afternoon". `now` is injectable so the bands are testable without a
        # clock-freezing dependency.
        hour = now_eastern(now).hour

        if 5 <= hour < 12:
            return "Good Morning"

        if 12 <= hour < 17:
            return "Good Afternoon"

        if 17 <= hour < 21:
            return "Good Evening"

        return "Good Night"