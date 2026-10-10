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
