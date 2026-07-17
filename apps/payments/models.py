from decimal import Decimal

from django.conf import settings
from django.db import models

from apps.common.enums import Currency, PaymentStatus
from apps.common.models import BaseModel


class Payment(BaseModel):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="payments",
    )

    provider = models.ForeignKey(
        "providers.Provider",
        on_delete=models.PROTECT,
        related_name="payments",
    )

    category = models.ForeignKey(
        "bill_categories.BillCategory",
        on_delete=models.PROTECT,
        related_name="payments",
    )

    amount = models.DecimalField(
        max_digits=18,
        decimal_places=2,
    )

    fee = models.DecimalField(
        max_digits=18,
        decimal_places=2,
        default=Decimal("0.00"),
    )

    total = models.DecimalField(
        max_digits=18,
        decimal_places=2,
    )

    currency = models.CharField(
        max_length=10,
        choices=Currency.choices,
        default=Currency.USD,
    )

    status = models.CharField(
        max_length=20,
        choices=PaymentStatus.choices,
        default=PaymentStatus.PENDING,
    )

    transaction_reference = models.CharField(
        max_length=100,
        unique=True,
    )

    provider_reference = models.CharField(
        max_length=100,
        blank=True,
    )

    payment_method = models.CharField(
        max_length=50,
    )

    class Meta:
        db_table = "payments"
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["user"]),
            models.Index(fields=["provider"]),
            models.Index(fields=["category"]),
            models.Index(fields=["status"]),
            models.Index(fields=["created_at"]),
            models.Index(fields=["transaction_reference"]),
        ]

    def __str__(self):
        return self.transaction_reference