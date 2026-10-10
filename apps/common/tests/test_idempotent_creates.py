"""API-2: the create endpoints a retry could duplicate honour
Idempotency-Key — the same key replays the first answer, and the work is
done once."""

from django.test import TestCase, override_settings
from rest_framework.test import APIClient

from apps.banking.models import BankConnection
from apps.billing.models import Subscription
from apps.vendors.factories import BillCategoryFactory, UserFactory, VendorFactory
from apps.vendors.models import Vendor, VendorPaymentMethod

NETWORK = {"method_type": "NETWORK", "network_payee_ref": "payee_1"}


class IdempotentCreateTests(TestCase):

    def setUp(self):
        self.user = UserFactory(is_active=True, is_verified=True)
        self.client = APIClient()
        self.client.force_authenticate(user=self.user)

    def _twice(self, url, body, key="key-1"):
        first = self.client.post(
            url, body, format="json", HTTP_IDEMPOTENCY_KEY=key
        )
        second = self.client.post(
            url, body, format="json", HTTP_IDEMPOTENCY_KEY=key
        )

        self.assertIn(first.status_code, (200, 201), first.content)
        self.assertEqual(second.status_code, first.status_code)
        self.assertEqual(second.json(), first.json())

        return first

    def test_subscribe(self):
        self._twice("/api/v1/billing/subscription", {"plan": "STANDARD"})

        self.assertEqual(
            Subscription.objects.filter(account=self.user).count(), 1
        )

    @override_settings(BANK_DATA_PROVIDER="mock")
    def test_bank_link_exchange(self):
        self._twice(
            "/api/v1/banking/link/exchange",
            {"public_token": "public-mock-chase", "consent_accepted": True},
        )

        self.assertEqual(
            BankConnection.objects.filter(user=self.user).count(), 1
        )

    def test_vendor_create(self):
        self._twice(
            "/api/v1/vendors",
            {"name": "WeWork", "source": "MANUAL",
             "category": str(BillCategoryFactory().id),
             "payment_method": NETWORK},
        )

        self.assertEqual(Vendor.objects.filter(user=self.user).count(), 1)

    def test_vendor_payment_method_create(self):
        vendor = VendorFactory(user=self.user)
        before = VendorPaymentMethod.objects.filter(vendor=vendor).count()

        self._twice(
            f"/api/v1/vendors/{vendor.id}/payment-methods",
            NETWORK,
        )

        self.assertEqual(
            VendorPaymentMethod.objects.filter(vendor=vendor).count(),
            before + 1,
        )

    def test_without_a_key_nothing_changes(self):
        first = self.client.post(
            "/api/v1/billing/subscription", {"plan": "STANDARD"},
            format="json",
        )
        second = self.client.post(
            "/api/v1/billing/subscription", {"plan": "STANDARD"},
            format="json",
        )

        self.assertEqual(first.status_code, 201)
        self.assertEqual(second.status_code, 400)
