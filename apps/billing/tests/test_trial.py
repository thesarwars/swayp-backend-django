"""The 14-day trial (Create Account screen, onboarding Step 2).

The signup screen promises "Free 14-day trial on the Business plan" and
"14-day free trial — no card needed", while the Founder card says "Pay $49 and
claim my spot". Those are not in conflict: a limited locked-rate seat is
claimed by paying for it, and the trial belongs to the standard business tier.
So the free period is a per-plan number, not a global one.

The entitlement stays ACTIVE throughout. A trial is a promise not to charge
yet, not a reduced product — gating features on it would make the free period
useless for evaluating the paid one.
"""

import datetime as dt

from django.test import TestCase, override_settings
from rest_framework.test import APIClient

from apps.billing.models import Plan, PlanCode, SubscriptionStatus
from apps.billing.services.provider_service import BillingProviderService
from apps.billing.services.subscription_service import SubscriptionService
from apps.vendors.factories import UserFactory

D = dt.date


def plan(code):
    return Plan.objects.get(code=code)


class PlanTrialSpecTests(TestCase):
    """The numbers, pinned where the BRD figures are pinned."""

    def test_standard_carries_the_fourteen_day_trial(self):
        self.assertEqual(plan(PlanCode.STANDARD).trial_days, 14)

    def test_founding_has_no_trial(self):
        """"Pay $49 and claim my spot" — the spot is claimed by paying."""
        self.assertEqual(plan(PlanCode.FOUNDING).trial_days, 0)

    def test_enterprise_has_no_trial(self):
        self.assertEqual(plan(PlanCode.ENTERPRISE).trial_days, 0)

    def test_the_seed_migration_applied_the_days(self):
        """The schema default is 0, so a database that had already seeded
        would silently offer no trial without the data step."""
        self.assertTrue(
            Plan.objects.filter(
                code=PlanCode.STANDARD, trial_days=14
            ).exists()
        )


class TrialLifecycleTests(TestCase):

    def setUp(self):
        self.service = SubscriptionService()
        self.today = D(2026, 9, 1)

    def subscribe(self, code, today=None):
        return self.service.subscribe(
            account=UserFactory(),
            plan_code=code,
            today=today or self.today,
        )

    def test_standard_gets_a_trial_end_fourteen_days_out(self):
        subscription = self.subscribe(PlanCode.STANDARD)

        self.assertEqual(subscription.trial_end, D(2026, 9, 15))

    def test_founding_gets_no_trial_end(self):
        self.assertIsNone(self.subscribe(PlanCode.FOUNDING).trial_end)

    def test_the_entitlement_is_active_during_the_trial(self):
        """Not a reduced product. Gating features on a trial makes the free
        period useless for evaluating the paid one."""
        subscription = self.subscribe(PlanCode.STANDARD)

        self.assertEqual(subscription.status, SubscriptionStatus.ACTIVE)
        self.assertTrue(subscription.is_active)

    def test_is_trialing_is_true_inside_the_window(self):
        subscription = self.subscribe(PlanCode.STANDARD)

        self.assertTrue(subscription.is_trialing(today=D(2026, 9, 14)))

    def test_is_trialing_is_false_on_the_end_date(self):
        """The 15th is the first charged day, not the last free one."""
        subscription = self.subscribe(PlanCode.STANDARD)

        self.assertFalse(subscription.is_trialing(today=D(2026, 9, 15)))

    def test_is_trialing_is_false_without_a_trial(self):
        subscription = self.subscribe(PlanCode.FOUNDING)

        self.assertFalse(subscription.is_trialing(today=self.today))

    def test_the_days_remaining_count_down(self):
        subscription = self.subscribe(PlanCode.STANDARD)

        self.assertEqual(
            subscription.trial_days_remaining(today=D(2026, 9, 1)), 14
        )
        self.assertEqual(
            subscription.trial_days_remaining(today=D(2026, 9, 13)), 2
        )

    def test_the_days_remaining_floor_at_zero(self):
        """A lapsed trial reads 0, never a negative."""
        subscription = self.subscribe(PlanCode.STANDARD)

        self.assertEqual(
            subscription.trial_days_remaining(today=D(2026, 10, 1)), 0
        )

    def test_no_trial_reports_none_not_zero(self):
        """None means "no trial"; 0 means "the trial just ended". A banner
        must be able to tell those apart."""
        subscription = self.subscribe(PlanCode.FOUNDING)

        self.assertIsNone(subscription.trial_days_remaining())

    def test_the_billing_cycle_is_unaffected(self):
        """The trial defers the charge; it does not move the period."""
        subscription = self.subscribe(PlanCode.STANDARD)

        self.assertEqual(subscription.period_start, D(2026, 9, 1))
        self.assertEqual(subscription.period_end, D(2026, 10, 1))

    def test_switching_off_a_trial_plan_keeps_the_recorded_end(self):
        """trial_end is a record of what was promised, not a live flag."""
        account = UserFactory()
        self.service.subscribe(
            account=account, plan_code=PlanCode.STANDARD, today=self.today
        )
        changed = self.service.change_plan(
            account=account, plan_code=PlanCode.ENTERPRISE
        )

        self.assertEqual(changed.trial_end, D(2026, 9, 15))


class TrialReachesTheProviderTests(TestCase):

    def test_the_provider_is_told_the_trial_length(self):
        from apps.billing.tests.test_stripe_billing import CollectingStub

        stub = CollectingStub()
        account = UserFactory()

        with override_settings(SUBSCRIPTION_BILLING_PROVIDER="mock"):
            service = SubscriptionService()
            service._provider = lambda: BillingProviderService(provider=stub)
            service.subscribe(
                account=account, plan_code=PlanCode.STANDARD
            )

        call = next(
            kw for name, kw in stub.calls if name == "create_subscription"
        )
        self.assertEqual(call["trial_days"], 14)

    def test_a_trial_needs_no_payment_method(self):
        """The screen says "no card needed", and a trialling subscription is
        valid without one until the trial ends."""
        from apps.billing.tests.test_stripe_billing import CollectingStub

        stub = CollectingStub()
        service = SubscriptionService()
        service._provider = lambda: BillingProviderService(provider=stub)

        subscription = service.subscribe(
            account=UserFactory(), plan_code=PlanCode.STANDARD
        )

        call = next(
            kw for name, kw in stub.calls if name == "create_subscription"
        )
        self.assertEqual(call["payment_method_id"], "")
        self.assertEqual(subscription.status, SubscriptionStatus.ACTIVE)

    def test_trialing_maps_to_active(self):
        from apps.billing.services.provider_service import swayp_status

        self.assertEqual(swayp_status("trialing"), "ACTIVE")


class TrialOnTheApiTests(TestCase):

    def setUp(self):
        self.user = UserFactory()
        self.client = APIClient()
        self.client.force_authenticate(user=self.user)

    def test_the_plans_list_advertises_the_trial(self):
        rows = {p["code"]: p for p in self.client.get(
            "/api/v1/billing/plans"
        ).data["data"]}

        self.assertEqual(rows["STANDARD"]["trial_days"], 14)
        self.assertEqual(rows["FOUNDING"]["trial_days"], 0)

    def test_the_subscription_reports_its_trial(self):
        self.client.post(
            "/api/v1/billing/subscription",
            {"plan": "STANDARD"},
            format="json",
        )

        data = self.client.get(
            "/api/v1/billing/subscription"
        ).data["data"]

        self.assertTrue(data["is_trialing"])
        self.assertEqual(data["trial_days_remaining"], 14)
        self.assertIsNotNone(data["trial_end"])

    def test_a_non_trial_plan_reports_no_trial(self):
        self.client.post(
            "/api/v1/billing/subscription",
            {"plan": "FOUNDING"},
            format="json",
        )

        data = self.client.get(
            "/api/v1/billing/subscription"
        ).data["data"]

        self.assertFalse(data["is_trialing"])
        self.assertIsNone(data["trial_end"])
        self.assertIsNone(data["trial_days_remaining"])

    def test_allowances_are_full_during_a_trial(self):
        """The point of a trial is evaluating the real product."""
        self.client.post(
            "/api/v1/billing/subscription",
            {"plan": "STANDARD"},
            format="json",
        )

        data = self.client.get(
            "/api/v1/billing/allowances"
        ).data["data"]

        self.assertEqual(data["SEATS"]["limit"], 10)
        self.assertEqual(data["CHECKS"]["limit"], 5)
