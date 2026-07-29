from django.conf import settings
from django.db import models

from apps.common.enums import NotificationType
from apps.common.models import BaseModel


class Notification(BaseModel):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="notifications",
    )

    title = models.CharField(
        max_length=255,
    )

    message = models.TextField()

    # 30 rather than 20 for parity with NotificationPreference.type: the two
    # columns store the same vocabulary and join on the string value, so a
    # future member of 21-30 chars would otherwise be storable as a
    # preference and unstorable as a notification.
    type = models.CharField(
        max_length=30,
        choices=NotificationType.choices,
        default=NotificationType.SYSTEM,
    )

    is_read = models.BooleanField(
        default=False,
    )

    read_at = models.DateTimeField(
        null=True,
        blank=True,
    )

    # Deep-link payload. A REMIND notification carries bill_id and
    # occurrence_id so tapping it opens the right approval screen (E6-S9),
    # rather than making the client parse the message text.
    metadata = models.JSONField(
        default=dict,
        blank=True,
    )

    class Meta:
        db_table = "notifications"
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["user"]),
            models.Index(fields=["is_read"]),
            models.Index(fields=["created_at"]),
            models.Index(fields=["type"]),
        ]

    def __str__(self):
        return self.title