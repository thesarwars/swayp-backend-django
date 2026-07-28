from django.db import models

from apps.common.enums import ScanStatus
from apps.common.models import BaseModel

from .bank_connection import BankConnection


class TransactionScan(BaseModel):
    """One pass over a connection's history looking for recurring bills."""

    connection = models.ForeignKey(
        BankConnection,
        on_delete=models.CASCADE,
        related_name="scans",
    )

    status = models.CharField(
        max_length=10,
        choices=ScanStatus.choices,
        default=ScanStatus.RUNNING,
    )

    # BRD §3.1 caps history at 12 months. The 24 months on screens
    # 836:8984/9052 is a design bug (PRD §11).
    months_history = models.PositiveSmallIntegerField(default=12)

    transactions_scanned = models.PositiveIntegerField(default=0)

    # Updated as detection runs so the progress screen can poll.
    detected_count = models.PositiveIntegerField(default=0)

    error_message = models.TextField(blank=True)

    completed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "transaction_scans"
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["connection", "status"]),
        ]

    def __str__(self):
        return f"scan {self.pk} ({self.status})"
