from django.conf import settings
from django.db import models

from apps.common.models import BaseModel


class IdempotencyKey(BaseModel):
    """Dedupe record for money-creating endpoints (E1-S7).

    Insert-first on the (user, endpoint, key) unique constraint wins races;
    a COMPLETED row replays its stored response; a same-key/different-body
    request is a 409.
    """

    class State(models.TextChoices):
        IN_PROGRESS = "IN_PROGRESS", "In progress"
        COMPLETED = "COMPLETED", "Completed"

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="idempotency_keys",
    )

    endpoint = models.CharField(max_length=100)

    key = models.CharField(max_length=100)

    request_hash = models.CharField(max_length=64)

    state = models.CharField(
        max_length=20,
        choices=State.choices,
        default=State.IN_PROGRESS,
    )

    response_status = models.PositiveSmallIntegerField(
        null=True,
        blank=True,
    )

    response_body = models.JSONField(
        null=True,
        blank=True,
    )

    class Meta:
        db_table = "idempotency_keys"
        constraints = [
            models.UniqueConstraint(
                fields=["user", "endpoint", "key"],
                name="uniq_idem_user_endpoint_key",
            )
        ]
        indexes = [
            models.Index(fields=["user", "endpoint", "key"]),
        ]

    def __str__(self):
        return f"{self.endpoint}:{self.key}"
