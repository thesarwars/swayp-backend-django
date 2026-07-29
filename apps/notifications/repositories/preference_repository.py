from apps.notifications.models import NotificationPreference


class NotificationPreferenceRepository:

    @staticmethod
    def get_queryset():
        return NotificationPreference.objects.all()

    def get(self, *, user, type):
        return (
            self.get_queryset()
            .filter(
                user=user,
                type=type,
            )
            .first()
        )

    def list_by_user(self, user):
        return self.get_queryset().filter(user=user)
