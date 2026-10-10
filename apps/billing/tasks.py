"""Subscription cycle rollover (E9-S1, E9-S2).

Daily beat job. Without it ``period_start`` never advances, and because the
metered counter is keyed on it, the free-check allowance never resets — a
Founding customer would get two free checks *ever* rather than two a month,
and every check after that would bill $2.99 forever. The cycle has to roll on
its own; nothing in the request path can do it.

Rolling the cycle is **not** charging for it. Stripe is not wired, so no money
moves here. Keeping the two separate is deliberate: the allowance is what the
customer is entitled to and it must be correct today, whereas collection can
arrive later without any of this changing shape.
"""

import logging

from celery import shared_task
from django.utils import timezone

from apps.billing.models import Subscription, SubscriptionStatus
from apps.billing.services.allowance_service import AllowanceService
from apps.billing.services.subscription_service import SubscriptionService

logger = logging.getLogger(__name__)


@shared_task(name="billing.renew_subscriptions")
def renew_subscriptions():
    """Advance every subscription whose cycle has ended.

    Safe to re-run and safe to miss a day: the loop keeps rolling a
    subscription until its period covers today, so a beat outage of a week
    catches up rather than leaving a customer a week behind.
    """
    today = timezone.localdate()
    subscriptions = SubscriptionService()
    allowances = AllowanceService()

    renewed = 0
    failed = 0
    ended = 0

    # Cancellations whose date has come end instead of renewing (BILLING-5).
    for subscription in Subscription.objects.filter(
        status__in=(SubscriptionStatus.ACTIVE, SubscriptionStatus.PAST_DUE),
        cancels_on__lte=today,
    ):
        if subscriptions.end_if_due(subscription, today=today):
            ended += 1

    due = Subscription.objects.filter(
        status=SubscriptionStatus.ACTIVE, period_end__lte=today
    ).select_related("plan")

    for subscription in due:
        try:
            # A missed run leaves more than one cycle outstanding. Bounded so
            # a bad date on one row cannot spin here forever.
            for _ in range(120):
                if subscription.period_end > today:
                    break

                subscriptions.renew(subscription, today=today)
                renewed += 1
            else:
                logger.warning(
                    "subscription %s still behind after 120 cycles; "
                    "check its period dates",
                    subscription.pk,
                )

            # Opens the new cycle's counters, which is what actually gives
            # the customer their checks back.
            allowances.reset_metered(subscription)

        except Exception:
            failed += 1
            logger.exception(
                "renewal failed for subscription %s", subscription.pk
            )

    if renewed or failed:
        logger.info(
            "subscription renewal: %s cycles rolled, %s failed",
            renewed,
            failed,
        )

    return {"renewed": renewed, "failed": failed, "ended": ended}
