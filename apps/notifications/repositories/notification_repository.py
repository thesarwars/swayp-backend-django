from django.utils import timezone

from apps.notifications.models import Notification


class NotificationRepository:

    @staticmethod
    def get_queryset():
        return Notification.objects.all()

    def list_by_user(self, user):
        return (
            self.get_queryset()
            .filter(user=user)
            .order_by("-created_at")
        )

    def get_by_id(self, *, user, notification_id):
        return (
            self.get_queryset()
            .filter(
                id=notification_id,
                user=user,
            )
            .first()
        )

    def unread_count(self, user):
        return (
            self.get_queryset()
            .filter(
                user=user,
                is_read=False,
            )
            .count()
        )

    def mark_as_read(self, notification):
        notification.is_read = True
        notification.read_at = timezone.now()

        notification.save(
            update_fields=[
                "is_read",
                "read_at",
                "updated_at",
            ]
        )

        return notification

    def mark_all_as_read(self, user):
        return (
            self.get_queryset()
            .filter(
                user=user,
                is_read=False,
            )
            .update(
                is_read=True,
                read_at=timezone.now(),
            )
        )