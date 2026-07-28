from django.conf import settings
from django.db import models

from apps.common.models import BaseModel


class PaymentBatch(BaseModel):
    """A group of payments that one authorization covers (E6-S1).

    "Bills (6)" on the confirm screen is a single batch: the user consents
    once and every payment inside inherits that consent.
    """

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="payment_batches",
    )

    total = models.DecimalField(max_digits=18, decimal_places=2)
    count = models.PositiveSmallIntegerField()

    class Meta:
        db_table = "payment_batches"
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["user", "-created_at"])]

    def __str__(self):
        return f"batch {self.pk} ({self.count} payments)"
