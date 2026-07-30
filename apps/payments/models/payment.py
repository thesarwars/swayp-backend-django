from decimal import Decimal

from django.conf import settings
from django.db import models

from apps.common.enums import (
    Currency,
    PaymentProcessor,
    PaymentRail,
    PaymentStatus,
)
from apps.common.models import BaseModel


class Payment(BaseModel):
    """One money movement, orchestrated by Swayp and executed by a provider.

    Non-custodial invariant (BRD §4): funds never rest in a Swayp-controlled
    balance. ``processor`` and ``provider_reference`` name the licensed party
    that actually moved the money, so any regulator question resolves to them.
    """

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="payments",
    )

    # Legacy catalog biller. Nullable since E6-S1 — a vendor-only payment has
    # no directory provider behind it.
    provider = models.ForeignKey(
        "providers.Provider",
        on_delete=models.PROTECT,
        related_name="payments",
        null=True,
        blank=True,
    )

    category = models.ForeignKey(
        "bill_categories.BillCategory",
        on_delete=models.PROTECT,
        related_name="payments",
        null=True,
        blank=True,
    )

    # The occurrence this payment settles. A retry is a new Payment against
    # the same occurrence, so this is deliberately not unique.
    bill_occurrence = models.ForeignKey(
        "bills.BillOccurrence",
        on_delete=models.SET_NULL,
        related_name="payments",
        null=True,
        blank=True,
    )

    vendor = models.ForeignKey(
        "vendors.Vendor",
        on_delete=models.PROTECT,
        related_name="payments",
        null=True,
        blank=True,
    )

    funding_account = models.ForeignKey(
        "banking.BankAccount",
        on_delete=models.PROTECT,
        related_name="payments",
        null=True,
        blank=True,
    )

    batch = models.ForeignKey(
        "payments.PaymentBatch",
        on_delete=models.SET_NULL,
        related_name="payments",
        null=True,
        blank=True,
    )

    rail = models.CharField(
        max_length=20,
        choices=PaymentRail.choices,
        default=PaymentRail.ACH_STANDARD,
    )

    # The licensed provider that executes this payment. Never surfaced to the
    # user except inside authorization text (E6-S3).
    processor = models.CharField(
        max_length=20,
        choices=PaymentProcessor.choices,
        default=PaymentProcessor.MOCK,
    )

    amount = models.DecimalField(max_digits=18, decimal_places=2)

    fee = models.DecimalField(
        max_digits=18,
        decimal_places=2,
        default=Decimal("0.00"),
    )

    total = models.DecimalField(max_digits=18, decimal_places=2)

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

    # SWP-YYYYMMDD-NNNN (apps/payments/models/reference.py).
    transaction_reference = models.CharField(max_length=100, unique=True)

    provider_reference = models.CharField(max_length=100, blank=True)

    payment_method = models.CharField(max_length=50, blank=True)

    # --- scheduling, all via the E1-S5 date engine ------------------------

    initiated_date = models.DateField(null=True, blank=True)
    estimated_arrival = models.DateField(null=True, blank=True)

    # Aware, America/New_York — "cancel before 11:59 PM EST today" is a wall
    # clock promise, so it cannot be stored as a naive or UTC-local date.
    cancellation_deadline = models.DateTimeField(null=True, blank=True)

    # Multi-entity scoping (E10-S3); null on single-entity accounts.
    entity = models.ForeignKey(
        "teams.Entity",
        on_delete=models.PROTECT,
        related_name="payments",
        null=True,
        blank=True,
    )

    # Future-dated send. Present means the payment waits for this date.
    scheduled_for = models.DateField(null=True, blank=True)

    # Paid-for faster delivery on the CHECK rail (E9-S3, $8.99). A real field
    # rather than a flag in failure_detail: it is an option the customer chose
    # and was billed for, so it has to survive on the payment and be
    # auditable next to the FeeCharge that references it.
    expedited = models.BooleanField(default=False)

    # --- failure ----------------------------------------------------------

    failure_reason = models.CharField(max_length=50, blank=True)
    failure_detail = models.JSONField(default=dict, blank=True)

    # Set when this payment replaces a failed one (E6-S6).
    retry_of = models.ForeignKey(
        "self",
        on_delete=models.SET_NULL,
        related_name="retries",
        null=True,
        blank=True,
    )

    # Key sent to the processor, persisted BEFORE the external call so a
    # crashed worker can query by it rather than blindly retrying (E6-S7).
    processor_idempotency_key = models.CharField(
        max_length=100,
        blank=True,
        db_index=True,
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
            models.Index(fields=["bill_occurrence"]),
            models.Index(fields=["batch"]),
            models.Index(fields=["vendor"]),
            models.Index(fields=["status", "scheduled_for"]),
        ]

    @property
    def is_terminal(self):
        return self.status in {
            PaymentStatus.SUCCESSFUL,
            PaymentStatus.FAILED,
            PaymentStatus.CANCELLED,
            PaymentStatus.REFUNDED,
            PaymentStatus.RETURNED,
        }

    @property
    def is_in_flight(self):
        return self.status in {
            PaymentStatus.SCHEDULED,
            PaymentStatus.PENDING,
            PaymentStatus.PROCESSING,
        }

    def __str__(self):
        return self.transaction_reference
