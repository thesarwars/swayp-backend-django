from django.conf import settings
from django.db import models

from apps.common.crypto import EncryptedTextField
from apps.common.models import BaseModel


class BankConnectionStatus(models.TextChoices):
    ACTIVE = "ACTIVE", "Active"
    DISCONNECTED = "DISCONNECTED", "Disconnected"
    ERROR = "ERROR", "Error"


class BankConnection(BaseModel):
    """A read-only link to one institution (E5-S1).

    The Plaid connection is also Swayp's identity check on its own paying
    customer (BRD §4) — proving the user owns the account. There is no
    separate KYC step.
    """

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="bank_connections",
    )

    provider = models.CharField(max_length=20, default="PLAID")

    item_id = models.CharField(max_length=100, unique=True)

    # Encrypted at rest and never serialized. This is the one legitimate use
    # of EncryptedTextField — a provider secret, not a bank number.
    access_token = EncryptedTextField()

    institution_name = models.CharField(max_length=100)
    institution_logo = models.URLField(max_length=500, blank=True)

    status = models.CharField(
        max_length=20,
        choices=BankConnectionStatus.choices,
        default=BankConnectionStatus.ACTIVE,
    )

    # ESIGN / Plaid disclosure timestamp. Required — a connection without
    # recorded consent is not one we can rely on.
    consented_at = models.DateTimeField()

    class Meta:
        db_table = "bank_connections"
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["user", "status"]),
        ]

    def __str__(self):
        return f"{self.institution_name} ({self.status})"
