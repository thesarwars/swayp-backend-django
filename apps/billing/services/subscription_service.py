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


#: Subscriptions the account currently holds. CANCELLED is the only state
#: that frees the account to subscribe again.
LIVE_STATUSES = (SubscriptionStatus.ACTIVE, SubscriptionStatus.PAST_DUE)


class SubscriptionService:

    def get_plan(self, code):
        plan = Plan.objects.filter(code=code, is_active=True).first()

        if plan is None:
            raise ValidationError({"plan": f"Unknown plan: {code}."})

        return plan

    def current(self, account):
        """The account's live subscription: ACTIVE, or PAST_DUE.

        PAST_DUE counts (BILLING-6). A failed card charge is something the
        customer fixes by replacing the card, and the plan stays in force
        meanwhile, as the billing webhook already intends. Treating it as
        "no subscription" made the account look planless everywhere: GET
        subscription answered null, plan limits fell back to the no-plan
        rules, fees were skipped, and subscribe would open a second
        subscription beside the unpaid one.
        """
        return (
            Subscription.objects.filter(
                account=account, status__in=LIVE_STATUSES
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

    def founding_spots_remaining(self):
        return max(FOUNDING_LOCK_LIMIT - self.founding_seats_taken(), 0)

    def trial_eligible(self, account):
        """A free trial is for an account's first subscription only
        (BILLING-4). Before, every new subscription started one, so cancel
        and resubscribe was a fresh free month, indefinitely."""
        return not Subscription.objects.filter(account=account).exists()

    @transaction.atomic
    def subscribe(self, *, account, plan_code, today=None,
                  payment_method_id=""):
        """Start a subscription, honouring the Founding price lock.

        ``payment_method_id`` comes from the client after it has collected a
        card against a SetupIntent, so the card itself never reaches Swayp.
        It is ignored when the provider collects nothing, which keeps every
        caller — tests, demos, the mock deployment — working unchanged.
        """
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

        # ACTIVE during the trial, deliberately. A trial is a promise not
        # to charge yet, not a reduced product, and gating features on it
        # would make the free period worthless for evaluating the paid one.
        trial_days = plan.trial_days if self.trial_eligible(account) else 0
        trial_end = (
            today + dt.timedelta(days=trial_days) if trial_days else None
        )

        subscription = Subscription.objects.create(
            account=account,
            plan=plan,
            status=SubscriptionStatus.ACTIVE,
            period_start=today,
            period_end=add_month(today),
            locked_price=locked_price,
            trial_end=trial_end,
        )

        self._provider().start(
            subscription,
            payment_method_id=payment_method_id,
            trial_days=trial_days,
        )

        return subscription

    def _provider(self):
        from apps.billing.services.provider_service import (
            BillingProviderService,
        )

        return BillingProviderService()

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

        self._assert_fits(subscription, plan)

        subscription.plan = plan
        subscription.locked_price = (
            subscription.locked_price
            if plan.price_locked and subscription.locked_price is not None
            else None
        )
        subscription.save(
            update_fields=["plan", "locked_price", "updated_at"]
        )

        # Provider-side move happens after the local one so a provider outage
        # cannot leave Swayp showing the old plan while the customer is billed
        # for the new one. The reverse mismatch is visible and reconcilable.
        self._provider().change_plan(subscription)

        return subscription

    @staticmethod
    def _assert_fits(subscription, plan):
        """Refuse a downgrade the account's usage would not fit (BILLING-7).

        It used to go through, leaving an account with three banks on a
        one-bank plan: over its limits from the moment it changed.
        """
        from apps.billing.services.allowance_service import AllowanceService
        from apps.common.exceptions import PlanLimitExceededException

        allowances = AllowanceService()
        over = allowances.overages_for_plan(subscription, plan)

        if not over:
            return

        parts = []

        for kind, used, limit in over:
            singular, plural = allowances.NOUN[kind]
            parts.append(
                f"{used} {singular if used == 1 else plural} in use, "
                f"{plan.name} allows {limit}"
            )

        raise PlanLimitExceededException(
            "This plan is too small for the account: "
            + "; ".join(parts)
            + ". Remove the extra ones first, or choose a bigger plan.",
            # The first ceiling the account is over; the message names all.
            limit=over[0][0],
        )

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
    def cancel(self, *, account, today=None):
        """Cancel at the end of the paid period (BILLING-5).

        It used to end the subscription at once, with no refund, so the
        customer lost the rest of the month they had paid for. Now the plan
        stays live until ``cancels_on`` and then ends; nothing is refunded
        because nothing is lost. The customer can withdraw it until then.
        """
        today = today or timezone.localdate()
        subscription = self.current(account)

        if subscription is None:
            raise ValidationError(
                {"subscription": "No active subscription to cancel."}
            )

        if subscription.cancels_on is not None:
            return subscription

        subscription.cancels_on = (
            subscription.trial_end
            if subscription.is_trialing(today)
            else subscription.period_end
        )
        subscription.cancelled_at = timezone.now()
        subscription.save(
            update_fields=["cancels_on", "cancelled_at", "updated_at"]
        )

        self._provider().schedule_cancel(subscription, cancel=True)

        return subscription

    @transaction.atomic
    def resume(self, *, account):
        """Withdraw a pending cancellation; the plan simply continues."""
        subscription = self.current(account)

        if subscription is None or subscription.cancels_on is None:
            raise ValidationError(
                {"subscription": "There is no pending cancellation to undo."}
            )

        subscription.cancels_on = None
        subscription.cancelled_at = None
        subscription.save(
            update_fields=["cancels_on", "cancelled_at", "updated_at"]
        )

        self._provider().schedule_cancel(subscription, cancel=False)

        return subscription

    @transaction.atomic
    def end_if_due(self, subscription, today=None):
        """End a subscription whose cancellation date has come. True if it
        ended. Stripe ends its side by itself and says so by webhook."""
        today = today or timezone.localdate()

        if subscription.cancels_on is None or subscription.cancels_on > today:
            return False

        subscription.status = SubscriptionStatus.CANCELLED
        subscription.save(update_fields=["status", "updated_at"])

        return True
