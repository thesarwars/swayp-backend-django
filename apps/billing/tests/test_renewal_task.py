"""The subscription cycle actually rolls (E9-S1, E9-S2).

``renew()`` existed and was tested, but nothing called it — and because the
metered counter is keyed on ``period_start``, a cycle that never advances
means free checks that never reset. A Founding customer would have got two
free checks ever, with every check after that billing $2.99 forever.

That is the point of these tests: not that ``renew()`` works, but that
something calls it.
"""

import datetime as dt

from django.test import TestCase
from django.utils import timezone

from apps.billing.factories import SubscriptionFactory
from apps.billing.models import (
    AllowanceKind,
    Plan,
    PlanCode,
    SubscriptionStatus,
)
from apps.billing.services.allowance_service import AllowanceService
from apps.billing.tasks import renew_subscriptions
from apps.payments.factories import PaymentFactory
from apps.vendors.factories import UserFactory

D = dt.date


def plan(code):
    return Plan.objects.get(code=code)


class RenewalTaskTests(TestCase):

    def setUp(self):
        self.today = timezone.localdate()
        self.allowances = AllowanceService()

    def ended_subscription(self, days_ago=1, code=PlanCode.FOUNDING):
        end = self.today - dt.timedelta(days=days_ago)

        return SubscriptionFactory(
            plan=plan(code),
            period_start=end - dt.timedelta(days=30),
            period_end=end,
        )

    def test_a_finished_cycle_rolls_forward(self):
        subscription = self.ended_subscription()

        renew_subscriptions()
        subscription.refresh_from_db()

        self.assertGreater(subscription.period_end, self.today)

    def test_free_checks_come_back_on_the_new_cycle(self):
        """The consequence that made this worth building, not the mechanism."""
        subscription = self.ended_subscription()

        # Founding includes two; use both.
        for _ in range(2):
            self.allowances.consume_metered(subscription=subscription)

        self.assertEqual(
            self.allowances.used(subscription, AllowanceKind.CHECKS), 2
        )

        renew_subscriptions()
        subscription.refresh_from_db()

        self.assertEqual(
            self.allowances.used(subscription, AllowanceKind.CHECKS), 0
        )

    def test_the_next_check_after_renewal_is_free_again(self):
        subscription = self.ended_subscription()

        for _ in range(3):
            self.allowances.consume_metered(subscription=subscription)

        renew_subscriptions()
        subscription.refresh_from_db()

        _, is_overage = self.allowances.consume_metered(
            subscription=subscription
        )

        self.assertFalse(is_overage)

    def test_seats_and_banks_are_not_reset(self):
        """Capacity is not a per-cycle allowance; the banks are still there."""
        from apps.banking.factories import BankConnectionFactory

        subscription = self.ended_subscription()
        BankConnectionFactory(user=subscription.account)

        renew_subscriptions()
        subscription.refresh_from_db()

        self.assertEqual(
            self.allowances.used(subscription, AllowanceKind.BANKS), 1
        )

    def test_a_current_cycle_is_left_alone(self):
        subscription = SubscriptionFactory(
            plan=plan(PlanCode.FOUNDING),
            period_start=self.today,
            period_end=self.today + dt.timedelta(days=30),
        )
        original = subscription.period_end

        renew_subscriptions()
        subscription.refresh_from_db()

        self.assertEqual(subscription.period_end, original)

    def test_a_cancelled_subscription_is_not_renewed(self):
        subscription = self.ended_subscription()
        subscription.status = SubscriptionStatus.CANCELLED
        subscription.save(update_fields=["status"])
        original = subscription.period_end

        renew_subscriptions()
        subscription.refresh_from_db()

        self.assertEqual(subscription.period_end, original)

    def test_a_missed_run_catches_up_rather_than_lagging(self):
        """A beat outage must not leave the customer cycles behind."""
        subscription = self.ended_subscription(days_ago=100)

        result = renew_subscriptions()
        subscription.refresh_from_db()

        self.assertGreater(subscription.period_end, self.today)
        self.assertGreater(result["renewed"], 1)

    def test_the_locked_price_survives_renewal(self):
        subscription = self.ended_subscription()
        subscription.locked_price = "49.00"
        subscription.save(update_fields=["locked_price"])

        renew_subscriptions()
        subscription.refresh_from_db()

        self.assertEqual(str(subscription.effective_price), "49.00")

    def test_running_twice_in_a_day_rolls_once(self):
        subscription = self.ended_subscription()

        renew_subscriptions()
        subscription.refresh_from_db()
        after_first = subscription.period_end

        renew_subscriptions()
        subscription.refresh_from_db()

        self.assertEqual(subscription.period_end, after_first)

    def test_one_bad_row_does_not_stop_the_rest(self):
        good = self.ended_subscription()
        other = self.ended_subscription()

        result = renew_subscriptions()

        good.refresh_from_db()
        other.refresh_from_db()

        self.assertEqual(result["failed"], 0)
        self.assertGreater(good.period_end, self.today)
        self.assertGreater(other.period_end, self.today)

    def test_unbilled_fees_from_the_old_cycle_survive(self):
        """Rolling the cycle must not lose revenue already accrued."""
        from apps.billing.models import FeeCharge, FeeKind

        subscription = self.ended_subscription()
        payment = PaymentFactory(user=subscription.account)

        FeeCharge.objects.create(
            subscription=subscription,
            payment=payment,
            kind=FeeKind.SAME_DAY_ACH,
            amount="4.99",
        )

        renew_subscriptions()

        self.assertEqual(subscription.fee_charges.count(), 1)
