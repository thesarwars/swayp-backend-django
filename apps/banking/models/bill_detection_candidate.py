from django.db import models

from apps.common.enums import BillFrequency
from apps.common.models import BaseModel

from .transaction_scan import TransactionScan


class BillDetectionCandidate(BaseModel):
    """A recurring pattern found in transaction history (E5-S4)."""

    scan = models.ForeignKey(
        TransactionScan,
        on_delete=models.CASCADE,
        related_name="candidates",
    )

    vendor_name = models.CharField(max_length=150)

    category_guess = models.ForeignKey(
        "bill_categories.BillCategory",
        on_delete=models.SET_NULL,
        related_name="detection_candidates",
        null=True,
        blank=True,
    )

    cadence = models.CharField(
        max_length=10,
        choices=BillFrequency.choices,
        default=BillFrequency.MONTHLY,
    )

    due_day = models.PositiveSmallIntegerField()

    amount = models.DecimalField(max_digits=18, decimal_places=2)

    # "3+ occurrences — confirmed pattern". Detection requires at least 3.
    occurrences = models.PositiveSmallIntegerField()

    selected = models.BooleanField(default=True)

    # Set once imported. Doubles as the idempotency marker: a candidate with
    # this set is skipped on a repeat import rather than duplicating the bill.
    imported_bill = models.ForeignKey(
        "bills.Bill",
        on_delete=models.SET_NULL,
        related_name="detection_candidates",
        null=True,
        blank=True,
    )

    class Meta:
        db_table = "bill_detection_candidates"
        ordering = ["-occurrences", "vendor_name"]
        constraints = [
            models.UniqueConstraint(
                fields=["scan", "vendor_name", "amount", "cadence"],
                name="uniq_candidate_per_scan",
            ),
        ]
        indexes = [
            models.Index(fields=["scan", "selected"]),
        ]

    @property
    def is_imported(self):
        return self.imported_bill_id is not None

    def __str__(self):
        return f"{self.vendor_name} {self.amount} x{self.occurrences}"
