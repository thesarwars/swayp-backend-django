"""Web B9: an ACH method is a processor token, never raw numbers (BRD
§3.4), and a made-up token is refused."""

from django.test import TestCase, override_settings
from rest_framework.test import APIClient

from apps.vendors.factories import UserFactory, VendorFactory
from apps.vendors.models import VendorPaymentMethod


class AchTokenTests(TestCase):

    def setUp(self):
        self.user = UserFactory()
        self.vendor = VendorFactory(user=self.user)
        self.client = APIClient()
        self.client.force_authenticate(user=self.user)

    def add(self, **body):
        return self.client.post(
            f"/api/v1/vendors/{self.vendor.id}/payment-methods",
            {"method_type": "ACH", "account_holder_name": "WeWork Inc",
             "account_last4": "1234", **body},
            format="json",
        )

    def test_a_made_up_token_is_refused(self):
        response = self.add(provider="STRIPE",
                            provider_token="yerter23424124asdasdad")

        self.assertEqual(response.status_code, 400)
        self.assertIn("provider_token", response.json()["errors"])

    def test_an_unknown_provider_is_refused(self):
        response = self.add(provider="ACME", provider_token="btok_1")

        self.assertIn("provider", response.json()["errors"])

    def test_a_real_shaped_token_is_accepted(self):
        response = self.add(provider="STRIPE", provider_token="btok_1N3a")

        self.assertEqual(response.status_code, 201, response.content)

    def test_raw_numbers_are_never_stored(self):
        """BRD §3.4: full numbers belong on the provider's systems only.
        Sent anyway, they are ignored, not kept."""
        self.add(provider="STRIPE", provider_token="btok_1N3a",
                 routing_number="021000021", account_number="000123456789")

        method = VendorPaymentMethod.objects.get(vendor=self.vendor)
        self.assertFalse(hasattr(method, "account_number"))

    @override_settings(MONEY_MOVEMENT_PROVIDER="stripe")
    def test_mock_tokens_are_refused_where_real_money_moves(self):
        response = self.add(provider="MOCK", provider_token="anything")

        self.assertIn("provider", response.json()["errors"])

    def test_mock_tokens_work_on_the_mock_processor(self):
        response = self.add(provider="MOCK", provider_token="anything")

        self.assertEqual(response.status_code, 201, response.content)
