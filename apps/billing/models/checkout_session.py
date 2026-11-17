from django.conf import settings
from django.db import models

from apps.common.models import BaseModel


class CheckoutStatus(models.TextChoices):
    OPEN = "open", "Open"
    COMPLETE = "complete", "Complete"
    EXPIRED = "expired", "Expired"


class CheckoutSession(BaseModel):
    """A Stripe-hosted Checkout page opened for an account's first payment.

    Kept so a second click reuses the open page instead of opening another,
    and so the success page, the webhook and a retry all fulfil the same
    row exactly once.
    """

    account = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="checkout_sessions",
    )
    plan = models.ForeignKey(
        "billing.Plan", on_delete=models.PROTECT, related_name="+"
    )
    provider_session_id = models.CharField(max_length=255, unique=True)
    url = models.URLField(max_length=2000, blank=True)
    status = models.CharField(
        max_length=20,
        choices=CheckoutStatus.choices,
        default=CheckoutStatus.OPEN,
    )
    expires_at = models.DateTimeField(null=True, blank=True)
    #: Set once fulfilled; the Subscription this checkout created.
    subscription = models.OneToOneField(
        "billing.Subscription",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="checkout_session",
    )

    class Meta:
        db_table = "billing_checkout_sessions"
        indexes = [models.Index(fields=["account", "status"])]
