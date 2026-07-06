from decimal import Decimal

from django.conf import settings
from django.core.validators import MinValueValidator
from django.db import models

from apps.common.enums import Currency, WalletStatus


class Wallet(models.Model):
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="wallet",
    )

    balance = models.DecimalField(
        max_digits=18,
        decimal_places=2,
        default=Decimal("0.00"),
        validators=[MinValueValidator(Decimal("0.00"))],
    )

    currency = models.CharField(
        max_length=10,
        choices=Currency.choices,
        default=Currency.BDT,
    )

    reward_points = models.PositiveIntegerField(default=0)

    cashback = models.DecimalField(
        max_digits=18,
        decimal_places=2,
        default=Decimal("0.00"),
    )

    status = models.CharField(
        max_length=20,
        choices=WalletStatus.choices,
        default=WalletStatus.ACTIVE,
    )

    is_balance_hidden = models.BooleanField(default=False)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "wallets"
        ordering = ["-updated_at"]
        indexes = [
            models.Index(fields=["user"]),
            models.Index(fields=["status"]),
        ]

    def __str__(self):
        return f"{self.user} Wallet"