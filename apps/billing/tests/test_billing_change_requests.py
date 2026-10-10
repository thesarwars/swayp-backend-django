"""The mobile team's billing change requests (BILLING-1 … BILLING-11)."""

import datetime as dt

from django.test import TestCase
from rest_framework.test import APIClient

from apps.billing.factories import SubscriptionFactory
from apps.billing.models import PlanCode, Subscription, SubscriptionStatus
from apps.billing.services.subscription_service import SubscriptionService
from apps.vendors.factories import UserFactory

D = dt.date


class BillingTestCase(TestCase):

    def setUp(self):
        self.user = UserFactory()
        self.client = APIClient()
        self.client.force_authenticate(user=self.user)
        self.service = SubscriptionService()

    def subscribe(self, plan=PlanCode.STANDARD, **kwargs):
        return self.service.subscribe(
            account=self.user, plan_code=plan, **kwargs
        )


class PastDueTests(BillingTestCase):
    """BILLING-6: a past-due subscription is still the account's plan."""

    def setUp(self):
        super().setUp()
        self.subscription = self.subscribe()
        self.subscription.status = SubscriptionStatus.PAST_DUE
        self.subscription.save(update_fields=["status"])

    def test_get_returns_it_flagged_past_due(self):
        data = self.client.get("/api/v1/billing/subscription").json()["data"]

        self.assertIsNotNone(data)
        self.assertEqual(data["status"], "PAST_DUE")
        self.assertTrue(data["past_due"])

    def test_it_still_counts_for_plan_limits(self):
        self.assertEqual(self.service.current(self.user), self.subscription)

    def test_a_second_subscription_is_refused(self):
        response = self.client.post(
            "/api/v1/billing/subscription",
            {"plan": PlanCode.FOUNDING},
            format="json",
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(Subscription.objects.filter(account=self.user).count(), 1)


class TrialEligibilityTests(BillingTestCase):
    """BILLING-4: one trial per account, and the plan list says so."""

    def plans(self):
        return {
            p["code"]: p
            for p in self.client.get("/api/v1/billing/plans").json()["data"]
        }

    def trial_plan(self):
        return next(
            code for code, p in self.plans().items() if p["trial_days"]
        )

    def test_a_new_account_is_offered_the_trial(self):
        code = self.trial_plan()

        self.assertTrue(self.plans()[code]["trial_eligible"])

    def test_resubscribing_after_cancel_gets_no_second_trial(self):
        code = self.trial_plan()
        first = self.subscribe(code)
        self.assertIsNotNone(first.trial_end)
        self.service.cancel(account=self.user)

        second = self.subscribe(code)

        self.assertIsNone(second.trial_end)
        self.assertFalse(self.plans()[code]["trial_eligible"])

    def test_the_founding_lock_reports_spots_left(self):
        founding = self.plans()[PlanCode.FOUNDING]

        self.assertTrue(founding["lock_available"])
        self.assertGreater(founding["founding_spots_remaining"], 0)
        self.assertIsNone(self.plans()[PlanCode.STANDARD]["founding_spots_remaining"])
