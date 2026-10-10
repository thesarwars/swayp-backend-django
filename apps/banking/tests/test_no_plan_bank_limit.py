"""BANK-1 — an account with no plan can link one bank, not unlimited.

The mobile app links a bank straight after sign-up, before any plan exists,
so the first link must work. Before this, "no subscription" skipped the gate
entirely and an account without a plan could link any number of banks.
"""

from django.test import TestCase, override_settings
from rest_framework.test import APIClient

from apps.banking.models import BankConnection, BankConnectionStatus
from apps.billing.factories import PlanFactory, SubscriptionFactory
from apps.vendors.factories import UserFactory

EXCHANGE_URL = "/api/v1/banking/link/exchange"


@override_settings(BANK_DATA_PROVIDER="mock")
class NoPlanBankLimitTests(TestCase):

    def setUp(self):
        self.user = UserFactory(is_active=True, is_verified=True)
        self.client = APIClient()
        self.client.force_authenticate(user=self.user)

    def _link(self, bank):
        return self.client.post(
            EXCHANGE_URL,
            {"public_token": f"public-mock-{bank}", "consent_accepted": True},
            format="json",
        )

    def test_the_first_bank_links_without_a_plan(self):
        self.assertEqual(self.client.post("/api/v1/banking/link/token").status_code, 200)
        self.assertEqual(self._link("chase").status_code, 201)

    def test_a_second_bank_needs_a_plan(self):
        self._link("chase")

        response = self._link("bofa")

        self.assertEqual(response.status_code, 402)
        self.assertEqual(response.json()["code"], "plan_limit")
        self.assertEqual(response.json()["limit"], "BANKS")
        self.assertEqual(
            BankConnection.objects.filter(user=self.user).count(), 1
        )

    def test_a_disconnected_bank_frees_the_slot(self):
        self._link("chase")
        BankConnection.objects.filter(user=self.user).update(
            status=BankConnectionStatus.DISCONNECTED
        )

        self.assertEqual(self._link("bofa").status_code, 201)

    def test_with_a_plan_the_plans_own_limit_applies(self):
        plan = PlanFactory()
        plan.bank_limit = 3
        plan.save(update_fields=["bank_limit"])
        SubscriptionFactory(account=self.user, plan=plan)

        for bank in ("chase", "bofa", "wellsfargo"):
            self.assertEqual(self._link(bank).status_code, 201)

        self.assertEqual(self._link("usbank").status_code, 402)
