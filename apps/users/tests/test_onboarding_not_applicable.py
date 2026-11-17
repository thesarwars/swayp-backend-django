"""Web B7: a step complete because it does not apply says so."""

from django.test import TestCase
from rest_framework.test import APIClient

from apps.users.models import AccountType, Profile
from apps.vendors.factories import UserFactory


class NotApplicableTests(TestCase):

    def steps(self, user):
        client = APIClient()
        client.force_authenticate(user=user)
        data = client.get("/api/v1/users/onboarding").json()["data"]
        return {s["key"]: s for s in data["steps"]}

    def test_individual_and_no_money(self):
        from apps.billing.services.subscription_service import (
            SubscriptionService,
        )

        user = UserFactory()
        Profile.objects.create(user=user, full_name="J",
                               account_type=AccountType.INDIVIDUAL)
        SubscriptionService().subscribe(account=user, plan_code="FOUNDING")

        steps = self.steps(user)

        self.assertEqual(steps["business"]["reason"], "individual_account")
        self.assertTrue(steps["business"]["not_applicable"])
        self.assertEqual(steps["payment"]["reason"], "no_payment_collected")
        self.assertFalse(steps["plan"]["not_applicable"])
        self.assertIsNone(steps["plan"]["reason"])

    def test_a_plan_from_before_billing_is_not_locked_out(self):
        """Dev accounts that subscribed while nothing was collected have no
        Stripe subscription; once collection is on they still pass step 3."""
        from unittest import mock

        from apps.billing.services.subscription_service import (
            SubscriptionService,
        )

        user = UserFactory()
        Profile.objects.create(user=user, full_name="J",
                               account_type=AccountType.INDIVIDUAL)
        SubscriptionService().subscribe(account=user, plan_code="FOUNDING")

        with mock.patch(
            "apps.billing.services.provider_service.BillingProviderService"
            ".collects_money",
            new_callable=mock.PropertyMock,
            return_value=True,
        ):
            steps = self.steps(user)

        self.assertTrue(steps["payment"]["complete"])
        self.assertEqual(steps["payment"]["reason"], "plan_predates_billing")
