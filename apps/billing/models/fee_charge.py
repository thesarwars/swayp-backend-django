from decimal import Decimal

from django.db import models

from apps.common.models import BaseModel


class FeeKind(models.TextChoices):
    SAME_DAY_ACH = "SAME_DAY_ACH", "Same-day ACH"
    EXPEDITED_CHECK = "EXPEDITED_CHECK", "Expedited check"
    CHECK_OVERAGE = "CHECK_OVERAGE", "Check overage"


class FeeState(models.TextChoices):
    PENDING = "PENDING", "Pending"
    BILLED = "BILLED", "Billed"
    REFUNDED = "REFUNDED", "Refunded"


#: BRD §6.2, verbatim. One source for the amounts, so a fee cannot drift.
FEE_AMOUNTS = {
    FeeKind.SAME_DAY_ACH: Decimal("4.99"),
    FeeKind.EXPEDITED_CHECK: Decimal("8.99"),
    FeeKind.CHECK_OVERAGE: Decimal("2.99"),
}

#: Fees carrying a delivery guarantee. Missing the guarantee auto-refunds
#: these (E9-S4); a check overage buys no speed promise, so it is excluded.
GUARANTEED_KINDS = (FeeKind.SAME_DAY_ACH, FeeKind.EXPEDITED_CHECK)


class FeeCharge(BaseModel):
    """One billable per-transaction fee (E9-S3).

    A ledger, not a mutable total: a refund transitions state rather than
    deleting the row, so "100% of missed guarantees refunded" stays
    measurable from the data (E9-S4 AC).
    """

    subscription = models.ForeignKey(
        "billing.Subscription",
        on_delete=models.PROTECT,
        related_name="fee_charges",
    )

    payment = models.ForeignKey(
        "payments.Payment",
        on_delete=models.PROTECT,
        related_name="fee_charges",
    )

    kind = models.CharField(max_length=20, choices=FeeKind.choices)

    amount = models.DecimalField(max_digits=18, decimal_places=2)

    state = models.CharField(
        max_length=20,
        choices=FeeState.choices,
        default=FeeState.PENDING,
    )

    # What Swayp promised when the fee was charged. Refund eligibility is
    # measured against this, not against a recomputed estimate — the promise
    # was made at charge time.
    guaranteed_arrival = models.DateField(null=True, blank=True)

    refunded_at = models.DateTimeField(null=True, blank=True)
    refund_reason = models.CharField(max_length=100, blank=True)

    class Meta:
        db_table = "fee_charges"
        ordering = ["-created_at"]
        constraints = [
            # One fee of a kind per payment. A retry that re-enters the fee
            # path must not double-charge.
            models.UniqueConstraint(
                fields=["payment", "kind"],
                name="uniq_fee_kind_per_payment",
            ),
        ]
        indexes = [
            models.Index(fields=["subscription", "state"]),
            models.Index(fields=["payment"]),
            models.Index(fields=["state", "guaranteed_arrival"]),
        ]

    @property
    def is_refundable(self):
        return (
            self.kind in GUARANTEED_KINDS
            and self.state != FeeState.REFUNDED
        )

    def __str__(self):
        return f"{self.kind} {self.amount} ({self.state})"
