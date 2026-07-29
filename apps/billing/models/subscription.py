from django.conf import settings
from django.db import models

from apps.common.models import BaseModel


class SubscriptionStatus(models.TextChoices):
    ACTIVE = "ACTIVE", "Active"
    PAST_DUE = "PAST_DUE", "Past due"
    CANCELLED = "CANCELLED", "Cancelled"


class Subscription(BaseModel):
    """One account's plan for one billing cycle (E9-S1)."""

    account = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="subscriptions",
    )

    plan = models.ForeignKey(
        "billing.Plan",
        on_delete=models.PROTECT,
        related_name="subscriptions",
    )

    status = models.CharField(
        max_length=20,
        choices=SubscriptionStatus.choices,
        default=SubscriptionStatus.ACTIVE,
    )

    period_start = models.DateField()
    period_end = models.DateField()

    # Set when the plan is price-locked. Renewal reads this rather than the
    # plan's current price, which is the whole point of the Founding lock.
    locked_price = models.DecimalField(
        max_digits=18,
        decimal_places=2,
        null=True,
        blank=True,
    )

    cancelled_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "subscriptions"
        ordering = ["-period_start"]
        constraints = [
            # One live subscription per account. Partial, so a history of
            # cancelled rows is still allowed.
            models.UniqueConstraint(
                fields=["account"],
                condition=models.Q(status="ACTIVE"),
                name="uniq_active_subscription_per_account",
            ),
        ]
        indexes = [
            models.Index(fields=["account", "status"]),
            models.Index(fields=["period_end"]),
        ]

    @property
    def effective_price(self):
        """What this subscription actually bills.

        The locked price wins when present — a Founding customer keeps $49
        even after the list price moves.
        """
        if self.locked_price is not None:
            return self.locked_price

        return self.plan.monthly_price

    @property
    def is_active(self):
        return self.status == SubscriptionStatus.ACTIVE

    def __str__(self):
        return f"{self.account_id} → {self.plan.code} ({self.status})"
