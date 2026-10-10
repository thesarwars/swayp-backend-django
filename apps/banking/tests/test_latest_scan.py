"""BANK-6 — a connection's latest scan can be found again.

A user who links a bank and leaves, or a client whose exchange answer was
lost, used to have no way back to the detected bills except starting a new
scan.
"""

from django.test import TestCase, override_settings
from rest_framework.test import APIClient

from apps.banking.models import TransactionScan
from apps.vendors.factories import UserFactory


@override_settings(BANK_DATA_PROVIDER="mock")
class LatestScanTests(TestCase):

    def setUp(self):
        self.client = APIClient()
        self.client.force_authenticate(user=UserFactory())

    def _link(self):
        return self.client.post(
            "/api/v1/banking/link/exchange",
            {"public_token": "public-mock-chase", "consent_accepted": True},
            format="json",
        ).json()["data"]

    def test_connections_carry_their_latest_scan(self):
        exchange = self._link()

        connection = self.client.get("/api/v1/banking/connections").json()["data"][0]

        self.assertEqual(connection["latest_scan"]["id"], exchange["scan"]["id"])
        self.assertIn("status", connection["latest_scan"])

    def test_a_rescan_becomes_the_latest(self):
        exchange = self._link()
        rescan = self.client.post(
            "/api/v1/banking/scans",
            {"connection_id": exchange["id"]},
            format="json",
        ).json()["data"]

        connection = self.client.get(
            f"/api/v1/banking/connections/{exchange['id']}"
        ).json()["data"]

        self.assertEqual(connection["latest_scan"]["id"], rescan["id"])

    def test_a_connection_with_no_scan_says_null(self):
        self._link()
        TransactionScan.objects.all().delete()

        connection = self.client.get("/api/v1/banking/connections").json()["data"][0]

        self.assertIsNone(connection["latest_scan"])

    def test_onboarding_summary_names_the_scan(self):
        exchange = self._link()

        detection = self.client.get(
            "/api/v1/banking/onboarding-summary"
        ).json()["data"]["detection"]

        self.assertEqual(detection["scan_id"], exchange["scan"]["id"])

    def test_listing_connections_is_one_query_for_scans(self):
        self._link()

        # The team-account lookup every request makes, then connections,
        # accounts and scans: one each, whatever the number of rows.
        with self.assertNumQueries(4):
            self.client.get("/api/v1/banking/connections")
