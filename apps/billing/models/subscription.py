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

    # When the free period ends, or null if there was never one. The
    # entitlement is ACTIVE throughout: a trial is a promise not to charge
    # yet, not a reduced product.
    trial_end = models.DateField(null=True, blank=True)

    # --- provider linkage (E9-S1) ---------------------------------------
    # Populated only when a real billing provider is collecting money.
    # Blank means the subscription is an entitlement Swayp granted and
    # nothing is being charged for it — which is exactly the state the
    # whole product ran in before Stripe was wired.
    provider_customer_id = models.CharField(max_length=100, blank=True)
    provider_subscription_id = models.CharField(
        max_length=100, blank=True, db_index=True
    )
    # The provider's own word for the state, kept verbatim next to Swayp's
    # status so a disagreement is visible rather than lost in translation.
    provider_status = models.CharField(max_length=30, blank=True)

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

    def is_trialing(self, today=None):
        """Still inside the free period.

        The entitlement is ACTIVE either way — this only says whether a
        charge has happened yet, which is what the "12 days left" banner
        needs and what a client must not infer from status alone.
        """
        if self.trial_end is None:
            return False

        from django.utils import timezone

        return (today or timezone.localdate()) < self.trial_end

    def trial_days_remaining(self, today=None):
        if self.trial_end is None:
            return None

        from django.utils import timezone

        return max((self.trial_end - (today or timezone.localdate())).days, 0)

    def __str__(self):
        return f"{self.account_id} → {self.plan.code} ({self.status})"
