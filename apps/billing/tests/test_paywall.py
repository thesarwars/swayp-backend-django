"""The paywall (D4): no live subscription, no product.

A user who signs up and backs out of Stripe Checkout has an account and no
plan. Product endpoints answer 402 ``subscription_required``; the endpoints
needed to buy a plan stay open.
"""

from django.test import TestCase, override_settings
from rest_framework.test import APIClient

from apps.billing.models import PlanCode, SubscriptionStatus
from apps.billing.services.subscription_service import SubscriptionService
from apps.vendors.factories import UserFactory


@override_settings(SUBSCRIPTION_REQUIRED=True)
class PaywallTests(TestCase):

    def setUp(self):
        self.user = UserFactory(is_active=True, is_verified=True)
        self.client = APIClient()
        self.client.force_authenticate(user=self.user)

    def subscribe(self):
        return SubscriptionService().subscribe(
            account=self.user, plan_code=PlanCode.STANDARD
        )

    def test_product_endpoints_answer_402_without_a_plan(self):
        for path in ("/api/v1/bills", "/api/v1/vendors", "/api/v1/dashboard/home"):
            with self.subTest(path=path):
                response = self.client.get(path)

                self.assertEqual(response.status_code, 402, path)
                self.assertEqual(response.data["code"], "subscription_required")
                self.assertIsNone(response.data["limit"])

    def test_buying_a_plan_stays_open(self):
        for path in (
            "/api/v1/billing/plans",
            "/api/v1/billing/subscription",
            "/api/v1/users/profile",
            "/api/v1/teams/me",
        ):
            with self.subTest(path=path):
                self.assertNotEqual(self.client.get(path).status_code, 402, path)

    def test_a_trial_opens_the_product(self):
        self.subscribe()

        self.assertEqual(self.client.get("/api/v1/bills").status_code, 200)

    def test_past_due_keeps_access(self):
        subscription = self.subscribe()
        subscription.status = SubscriptionStatus.PAST_DUE
        subscription.save()

        self.assertEqual(self.client.get("/api/v1/bills").status_code, 200)

    def test_cancelled_loses_access(self):
        subscription = self.subscribe()
        subscription.status = SubscriptionStatus.CANCELLED
        subscription.save()

        self.assertEqual(self.client.get("/api/v1/bills").status_code, 402)

    def test_a_teammate_is_covered_by_the_owners_plan(self):
        from apps.teams.factories import ActiveMemberFactory

        self.subscribe()
        mate = ActiveMemberFactory(account=self.user).user

        client = APIClient()
        client.force_authenticate(user=mate)
        self.assertEqual(client.get("/api/v1/bills").status_code, 200)
