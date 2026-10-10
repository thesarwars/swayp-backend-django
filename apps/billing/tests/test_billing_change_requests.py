"""The mobile team's billing change requests (BILLING-1 … BILLING-11)."""

import datetime as dt

from django.test import TestCase
from rest_framework.test import APIClient

from apps.billing.factories import SubscriptionFactory
from apps.billing.models import (
    Plan,
    PlanCode,
    Subscription,
    SubscriptionStatus,
)
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
        cancelled = self.service.cancel(account=self.user)
        self.service.end_if_due(cancelled, today=cancelled.cancels_on)

        second = self.subscribe(code)

        self.assertIsNone(second.trial_end)
        self.assertFalse(self.plans()[code]["trial_eligible"])

    def test_the_founding_lock_reports_spots_left(self):
        founding = self.plans()[PlanCode.FOUNDING]

        self.assertTrue(founding["lock_available"])
        self.assertGreater(founding["founding_spots_remaining"], 0)
        self.assertIsNone(self.plans()[PlanCode.STANDARD]["founding_spots_remaining"])


class CancelAtPeriodEndTests(BillingTestCase):
    """BILLING-5: cancelling keeps the paid period, and can be undone."""

    def setUp(self):
        super().setUp()
        self.subscription = self.subscribe(PlanCode.FOUNDING, today=D(2026, 8, 1))

    def test_cancel_keeps_the_plan_until_the_period_ends(self):
        response = self.client.delete("/api/v1/billing/subscription")

        self.assertEqual(response.status_code, 200)
        data = response.json()["data"]
        self.assertEqual(data["status"], "ACTIVE")
        self.assertTrue(data["cancel_pending"])
        self.assertEqual(data["cancels_on"], "2026-09-01")
        self.assertEqual(self.service.current(self.user), self.subscription)

    def test_resume_withdraws_it(self):
        self.client.delete("/api/v1/billing/subscription")

        response = self.client.post("/api/v1/billing/subscription/resume")

        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.json()["data"]["cancel_pending"])
        self.assertIsNone(response.json()["data"]["cancels_on"])

    def test_resume_without_a_pending_cancel_is_a_400(self):
        self.assertEqual(
            self.client.post("/api/v1/billing/subscription/resume").status_code,
            400,
        )

    def test_the_daily_job_ends_it_on_the_date(self):
        from unittest.mock import patch

        from apps.billing.tasks import renew_subscriptions

        self.client.delete("/api/v1/billing/subscription")

        with patch("django.utils.timezone.localdate", return_value=D(2026, 9, 1)):
            result = renew_subscriptions()

        self.subscription.refresh_from_db()
        self.assertEqual(result["ended"], 1)
        self.assertEqual(self.subscription.status, SubscriptionStatus.CANCELLED)

    def test_a_trial_cancel_ends_with_the_trial(self):
        account = UserFactory()
        trial_plan = Plan.objects.filter(trial_days__gt=0).first().code
        subscription = self.service.subscribe(
            account=account, plan_code=trial_plan, today=D(2026, 8, 1)
        )

        cancelled = self.service.cancel(account=account, today=D(2026, 8, 3))

        self.assertEqual(cancelled.cancels_on, subscription.trial_end)
