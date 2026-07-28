from django.db import models

from apps.common.models import BaseModel


class AuditLog(BaseModel):

    user = models.ForeignKey(
        "users.User",
        on_delete=models.SET_NULL,
        null=True,
    )

    action = models.CharField(
        max_length=255,
    )

    # Nullable so a caller that cannot determine the client IP records that
    # fact instead of filing a placeholder. A consent artifact with a
    # fabricated IP is worse than one that admits the gap
    # (apps/common/request_meta.py).
    ip = models.GenericIPAddressField(null=True, blank=True)

    user_agent = models.TextField()

    metadata = models.JSONField(
        default=dict,
    )

    class Meta:
        db_table = "audit_logs"
        ordering = ["-created_at"]

        # The three ways anyone ever asks this table a question: what did this
        # user do, who did X, and what happened in this window. Without them
        # producing a consent record on demand means a full scan of every
        # audit row ever written.
        indexes = [
            models.Index(fields=["user", "-created_at"]),
            models.Index(fields=["action", "-created_at"]),
            models.Index(fields=["-created_at"]),
        ]