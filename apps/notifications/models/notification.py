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

    # E8-S4. Idempotency handle for notifications emitted on a schedule:
    # "<TYPE>:<occurrence-id>:<eastern-date>". NULL for event-driven rows — a
    # webhook PAYMENT_FAILED is a real event every time it happens — and NULLs
    # do not collide under the partial constraint below.
    dedupe_key = models.CharField(
        max_length=120,
        null=True,
        blank=True,
        default=None,
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
        # The condition is not redundant with "NULLs are distinct": it keeps
        # the index off the event-driven rows, which are the overwhelming
        # majority, and it states the intent so a later default="" cannot
        # silently turn every undeduped row into a collision.
        constraints = [
            models.UniqueConstraint(
                fields=["dedupe_key"],
                condition=models.Q(dedupe_key__isnull=False),
                name="uniq_notification_dedupe_key",
            ),
        ]

    def __str__(self):
        return self.title