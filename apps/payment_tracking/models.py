from django.db import models

from apps.common.enums import PaymentStatus
from apps.common.models import BaseModel


class PaymentTracking(BaseModel):
    payment = models.OneToOneField(
        "payments.Payment",
        on_delete=models.CASCADE,
        related_name="tracking",
    )

    status = models.CharField(
        max_length=20,
        choices=PaymentStatus.choices,
        default=PaymentStatus.PENDING,
    )

    estimated_completion = models.DateTimeField(
        null=True,
        blank=True,
    )

    class Meta:
        db_table = "payment_tracking"
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["payment"]),
            models.Index(fields=["status"]),
            models.Index(fields=["created_at"]),
        ]

    def __str__(self):
        return self.payment.transaction_reference