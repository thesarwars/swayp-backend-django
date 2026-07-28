from django.db import models

from apps.common.enums import BankAccountType
from apps.common.models import BaseModel

from .bank_connection import BankConnection


class BankAccount(BaseModel):
    """One account inside a connection. Only the mask is ever exposed."""

    connection = models.ForeignKey(
        BankConnection,
        on_delete=models.CASCADE,
        related_name="accounts",
    )

    external_id = models.CharField(max_length=100)

    name = models.CharField(max_length=100)

    # Last four only — the full number never reaches Swayp.
    mask = models.CharField(max_length=4)

    account_type = models.CharField(
        max_length=10,
        choices=BankAccountType.choices,
        default=BankAccountType.CHECKING,
    )

    is_default_funding_source = models.BooleanField(default=False)

    # Provider-keyed handles, e.g. {"moov_funding_source_id": "..."}.
    processor_refs = models.JSONField(default=dict, blank=True)

    available_balance = models.DecimalField(
        max_digits=18, decimal_places=2, null=True, blank=True
    )
    current_balance = models.DecimalField(
        max_digits=18, decimal_places=2, null=True, blank=True
    )
    balance_as_of = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "bank_accounts"
        ordering = ["-is_default_funding_source", "name"]
        constraints = [
            models.UniqueConstraint(
                fields=["connection", "external_id"],
                name="uniq_account_per_connection",
            ),
        ]
        indexes = [
            models.Index(fields=["connection"]),
        ]

    @property
    def masked_name(self):
        return f"{self.name} ****{self.mask}"

    def __str__(self):
        return self.masked_name
