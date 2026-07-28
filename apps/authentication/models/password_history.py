from django.conf import settings
from django.db import models

from apps.common.models import BaseModel


class PasswordHistory(BaseModel):
    """Previous password hashes, so a reset cannot reuse one (E2-S4)."""

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="password_history",
    )

    password_hash = models.CharField(max_length=255)

    class Meta:
        db_table = "password_history"
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["user", "-created_at"]),
        ]

    def __str__(self):
        return f"{self.user_id} @ {self.created_at:%Y-%m-%d}"
