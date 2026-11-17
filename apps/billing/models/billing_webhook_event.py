from django.db import models

from apps.common.models import BaseModel


class BillingWebhookEvent(BaseModel):
    """A Stripe billing event already applied.

    Stripe delivers at least once. Handlers are written to be safe twice,
    but creating a subscription from a checkout must never depend on that
    alone: an event id seen before is acknowledged and skipped.
    """

    event_id = models.CharField(max_length=255, unique=True)
    type = models.CharField(max_length=100)

    class Meta:
        db_table = "billing_webhook_events"
