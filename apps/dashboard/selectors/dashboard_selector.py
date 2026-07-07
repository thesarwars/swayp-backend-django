from apps.dashboard.repositories import DashboardRepository


class DashboardSelector:

    def __init__(self):
        self.repository = DashboardRepository()

    def get_user(self, user_id):
        return self.repository.get_user(user_id)

    def get_unread_notification_count(
        self,
        user,
    ):
        return self.repository.get_unread_notification_count(
            user
        )