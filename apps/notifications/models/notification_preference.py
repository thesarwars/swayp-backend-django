from django.conf import settings
from django.db import models

from apps.common.enums import NotificationType
from apps.common.models import BaseModel

#: Preference columns, in display order. The single source of truth for what a
#: "channel" is on the persistence side; the delivery side registers an adapter
#: against one of these names (apps/notifications/channels/).
CHANNEL_FIELDS = ("in_app", "email", "sms", "push")


class NotificationPreference(BaseModel):
    """One user's per-type channel switches (E8-S3).

    A missing row is not "no preference recorded" — it is "the defaults
    apply". Nothing materialises a row on read, so "never chose" stays
    distinguishable from "chose the value that happens to be the default",
    and changing a default later still reaches everyone who never touched it.
    """

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="notification_preferences",
    )

    type = models.CharField(
        max_length=30,
        choices=NotificationType.choices,
    )

    in_app = models.BooleanField(default=True)
    email = models.BooleanField(default=True)
    # BRD §1.2: SMS and push are reserved columns with no delivery adapter
    # this release. Default off, and the API refuses to set them on, so a
    # stored true can never imply a message the product cannot send.
    sms = models.BooleanField(default=False)
    push = models.BooleanField(default=False)

    class Meta:
        db_table = "notification_preferences"
        # No separate index on user: uniq_pref_per_type is a btree on
        # (user, type) with user leading, so both filter(user=…) and
        # filter(user=…, type=…) are already served.
        constraints = [
            models.UniqueConstraint(
                fields=["user", "type"],
                name="uniq_pref_per_type",
            )
        ]

    def __str__(self):
        return f"{self.user_id}:{self.type}"
