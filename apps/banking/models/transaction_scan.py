from django.db import models

from apps.common.enums import ScanErrorCode, ScanStatus
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

    # 24, decided 2026-08-25, and it overrides the BRD rather than following
    # it: BRD §3.1 says "up to 12 months" and PRD §11 open question 2 called
    # the 24 on screens 836:8984/9052 a design bug. The screens won — every
    # bank-connect screen promises 24 months and Plaid serves that window
    # without complaint, so the requirement moved to match what was designed.
    months_history = models.PositiveSmallIntegerField(default=24)

    transactions_scanned = models.PositiveIntegerField(default=0)

    # Updated as detection runs so the progress screen can poll.
    detected_count = models.PositiveIntegerField(default=0)

    error_message = models.TextField(blank=True)

    # Set with status FAILED, blank otherwise (BANK-9).
    error_code = models.CharField(
        max_length=30,
        choices=ScanErrorCode.choices,
        blank=True,
        default="",
    )

    completed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "transaction_scans"
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["connection", "status"]),
        ]

    def __str__(self):
        return f"scan {self.pk} ({self.status})"
