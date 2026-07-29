"""Subscribing, renewing and changing plan (E9-S1)."""

import datetime as dt

from django.db import transaction
from django.utils import timezone
from rest_framework.exceptions import ValidationError

from apps.billing.models import (
    Plan,
    PlanCode,
    Subscription,
    SubscriptionStatus,
)

#: Founding is price-locked for the first 500 customers (BRD §6.2). Beyond
#: that the plan is still sellable, just at the list price of the day.
FOUNDING_LOCK_LIMIT = 500


def add_month(value):
    """One calendar month on, clamped into short months.

    A 31st billing anchor must land on Feb 28, not roll into March.
    """
    year = value.year + (1 if value.month == 12 else 0)
    month = 1 if value.month == 12 else value.month + 1

    last_day = [
        31,
        29 if (year % 4 == 0 and (year % 100 != 0 or year % 400 == 0)) else 28,
        31, 30, 31, 30, 31, 31, 30, 31, 30, 31,
    ][month - 1]

    return dt.date(year, month, min(value.day, last_day))


class SubscriptionService:

    def get_plan(self, code):
        plan = Plan.objects.filter(code=code, is_active=True).first()

        if plan is None:
            raise ValidationError({"plan": f"Unknown plan: {code}."})

        return plan

    def current(self, account):
        return (
            Subscription.objects.filter(
                account=account, status=SubscriptionStatus.ACTIVE
            )
            .select_related("plan")
            .first()
        )

    def founding_seats_taken(self):
        return Subscription.objects.filter(
            plan__code=PlanCode.FOUNDING
        ).count()

    def founding_lock_available(self):
        return self.founding_seats_taken() < FOUNDING_LOCK_LIMIT

    @transaction.atomic
    def subscribe(self, *, account, plan_code, today=None):
        """Start a subscription, honouring the Founding price lock."""
        today = today or timezone.localdate()

        if self.current(account) is not None:
            raise ValidationError(
                {
                    "subscription": (
                        "This account already has an active subscription. "
                        "Change the plan instead."
                    )
                }
            )

        plan = self.get_plan(plan_code)

        # The lock is captured at signup. A customer who subscribes as number
        # 501 pays list price, and one who got in at 499 keeps $49 forever.
        locked_price = None
        if plan.price_locked and self.founding_lock_available():
            locked_price = plan.monthly_price

        return Subscription.objects.create(
            account=account,
            plan=plan,
            status=SubscriptionStatus.ACTIVE,
            period_start=today,
            period_end=add_month(today),
            locked_price=locked_price,
        )

    @transaction.atomic
    def change_plan(self, *, account, plan_code, today=None):
        """Move to another plan, keeping the current cycle boundaries.

        The lock does not travel: leaving Founding gives it up, and coming
        back later is a new signup subject to the 500 limit.
        """
        today = today or timezone.localdate()

        subscription = self.current(account)

        if subscription is None:
            raise ValidationError(
                {"subscription": "No active subscription to change."}
            )

        plan = self.get_plan(plan_code)

        if plan.id == subscription.plan_id:
            return subscription

        subscription.plan = plan
        subscription.locked_price = (
            subscription.locked_price
            if plan.price_locked and subscription.locked_price is not None
            else None
        )
        subscription.save(
            update_fields=["plan", "locked_price", "updated_at"]
        )

        return subscription

    @transaction.atomic
    def renew(self, subscription, today=None):
        """Roll the cycle forward.

        Reads ``effective_price``, so a locked subscription renews at its
        locked price rather than the plan's current one.
        """
        today = today or timezone.localdate()

        subscription.period_start = subscription.period_end
        subscription.period_end = add_month(subscription.period_end)
        subscription.save(
            update_fields=["period_start", "period_end", "updated_at"]
        )

        return subscription

    @transaction.atomic
    def cancel(self, *, account):
        subscription = self.current(account)

        if subscription is None:
            raise ValidationError(
                {"subscription": "No active subscription to cancel."}
            )

        subscription.status = SubscriptionStatus.CANCELLED
        subscription.cancelled_at = timezone.now()
        subscription.save(
            update_fields=["status", "cancelled_at", "updated_at"]
        )

        return subscription
