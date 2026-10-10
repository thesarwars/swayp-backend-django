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
