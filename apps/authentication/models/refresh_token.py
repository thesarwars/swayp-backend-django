from django.db import models

from apps.common.models import BaseModel


class RefreshToken(BaseModel):

    user = models.ForeignKey(
        "users.User",
        on_delete=models.CASCADE,
        related_name="refresh_tokens",
    )

    token_hash = models.CharField(
        max_length=255,
    )

    user_agent = models.TextField()

    ip_address = models.GenericIPAddressField()

    expires_at = models.DateTimeField()

    revoked_at = models.DateTimeField(
        null=True,
        blank=True,
    )

    class Meta:
        db_table = "refresh_tokens"