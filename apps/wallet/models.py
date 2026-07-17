from decimal import Decimal

from django.conf import settings
from django.core.validators import MinValueValidator
from django.db import models

from apps.common.enums import Currency, WalletStatus,PaymentStatus
from apps.common.models import BaseModel

class Wallet(BaseModel):
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
        default=Currency.USD,
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

    

    class Meta:
        db_table = "wallets"
        ordering = ["-updated_at"]
        indexes = [
            models.Index(fields=["user"]),
            models.Index(fields=["status"]),
        ]

    def __str__(self):
        return f"{self.user} Wallet"
    

class WalletTransaction(BaseModel):
    wallet = models.ForeignKey(
        Wallet,
        on_delete=models.CASCADE,
        related_name="transactions",
    )

    payment = models.OneToOneField(
        "payments.Payment",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="wallet_transaction",
    )

    amount = models.DecimalField(
        max_digits=18,
        decimal_places=2,
    )

    balance_before = models.DecimalField(
        max_digits=18,
        decimal_places=2,
    )

    balance_after = models.DecimalField(
        max_digits=18,
        decimal_places=2,
    )

    transaction_type = models.CharField(max_length=30)

    status = models.CharField(
        max_length=20,
        choices=PaymentStatus.choices,
        default=PaymentStatus.SUCCESSFUL,
    )

    reference = models.CharField(
        max_length=100,
        unique=True,
    )

    description = models.TextField(blank=True)

    

    class Meta:
        db_table = "wallet_transactions"
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["wallet"]),
            models.Index(fields=["reference"]),
            models.Index(fields=["created_at"]),
        ]

    def __str__(self):
        return self.reference