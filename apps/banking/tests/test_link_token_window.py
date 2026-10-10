"""BANK-4 — link/token says how much history the scan will read.

The screens before the link promise a window ("Returns 24 months of
history"). Returning it here lets that copy come from the same constant the
scan uses, instead of a number hard-coded in the app.
"""

from django.test import TestCase, override_settings
from rest_framework.test import APIClient

from apps.banking.services.scan_service import MAX_MONTHS_HISTORY
from apps.vendors.factories import UserFactory


@override_settings(BANK_DATA_PROVIDER="mock")
class LinkTokenWindowTests(TestCase):

    def test_link_token_returns_the_scan_window(self):
        client = APIClient()
        client.force_authenticate(user=UserFactory())

        data = client.post("/api/v1/banking/link/token").json()["data"]

        self.assertEqual(data["months_history"], 24)
        self.assertEqual(data["months_history"], MAX_MONTHS_HISTORY)

    def test_the_scan_reads_the_window_link_token_promised(self):
        client = APIClient()
        client.force_authenticate(user=UserFactory())

        promised = client.post("/api/v1/banking/link/token").json()["data"]
        exchange = client.post(
            "/api/v1/banking/link/exchange",
            {"public_token": "public-mock-chase", "consent_accepted": True},
            format="json",
        ).json()["data"]

        self.assertEqual(
            exchange["scan"]["months_history"], promised["months_history"]
        )


@override_settings(BANK_DATA_PROVIDER="mock")
class LinkTokenPlatformParamTests(TestCase):
    """BANK-5: the platform reaches the provider, and a bad one is a 400."""

    def setUp(self):
        self.client = APIClient()
        self.client.force_authenticate(user=UserFactory())

    def test_platform_is_passed_to_the_provider(self):
        from unittest.mock import patch

        from integrations.bank_data.mock import MockBankDataProvider

        with patch.object(
            MockBankDataProvider,
            "create_link_token",
            autospec=True,
            side_effect=MockBankDataProvider.create_link_token,
        ) as spy:
            response = self.client.post(
                "/api/v1/banking/link/token", {"platform": "android"},
                format="json",
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(spy.call_args.kwargs["platform"], "android")

    def test_no_body_still_works(self):
        self.assertEqual(
            self.client.post("/api/v1/banking/link/token").status_code, 200
        )

    def test_an_unknown_platform_is_a_400(self):
        response = self.client.post(
            "/api/v1/banking/link/token", {"platform": "windows"},
            format="json",
        )

        self.assertEqual(response.status_code, 400)
