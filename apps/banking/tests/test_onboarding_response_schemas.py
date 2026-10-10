"""BANK-2 — the published response schemas match what the server sends.

The schemas are hand-written descriptions of bodies built elsewhere, so they
can drift. These tests compare the keys of real responses with the fields the
schema declares, at every level.
"""

from django.test import TestCase, override_settings
from rest_framework.test import APIClient

from apps.bill_categories.models import BillCategory
from apps.banking.api.serializers.onboarding import (
    ImportReportSerializer,
    OnboardingSummarySerializer,
)
from apps.users.api.serializers.onboarding import OnboardingStateSerializer
from apps.vendors.factories import UserFactory


def assert_same_shape(test, body, serializer):
    """Every declared field is present and nothing undeclared is sent."""
    fields = serializer.fields
    required = {name for name, field in fields.items() if field.required}

    test.assertTrue(required <= set(body), (required - set(body)))
    test.assertTrue(set(body) <= set(fields), (set(body) - set(fields)))

    for name, value in body.items():
        field = fields[name]
        child = getattr(field, "child", None)

        if hasattr(field, "fields") and isinstance(value, dict):
            assert_same_shape(test, value, field)
        elif child is not None and hasattr(child, "fields"):
            for item in value:
                assert_same_shape(test, item, child)


@override_settings(BANK_DATA_PROVIDER="mock")
class OnboardingResponseSchemaTests(TestCase):

    def setUp(self):
        self.user = UserFactory(is_active=True, is_verified=True)
        self.client = APIClient()
        self.client.force_authenticate(user=self.user)
        # Import files a bill with no better category under "Other".
        BillCategory.objects.create(
            name="Other", icon="https://e.com/i.png", color="#111"
        )

        # Runs the scan the exchange queues, so there are bills to import.
        with self.captureOnCommitCallbacks(execute=True):
            exchange = self.client.post(
                "/api/v1/banking/link/exchange",
                {"public_token": "public-mock-chase", "consent_accepted": True},
                format="json",
            )
        self.scan_id = exchange.json()["data"]["scan"]["id"]

    def test_onboarding_summary(self):
        body = self.client.get("/api/v1/banking/onboarding-summary").json()

        assert_same_shape(self, body["data"], OnboardingSummarySerializer())
        self.assertIsNotNone(body["data"]["connection"])

    def test_summary_counts_months_and_bills(self):
        """BANK-7: the window of the newest scan, and the bills/summary total."""
        self.client.post(
            f"/api/v1/banking/scans/{self.scan_id}/import",
            {"all": True},
            format="json",
        )

        data = self.client.get("/api/v1/banking/onboarding-summary").json()["data"]
        bills_summary = self.client.get("/api/v1/bills/summary").json()["data"]

        self.assertEqual(data["detection"]["months_history"], 24)
        self.assertGreater(data["bills"]["total_bills"], 0)
        self.assertEqual(
            data["bills"]["total_bills"], bills_summary["total_bills"]
        )

    def test_months_history_is_null_before_any_scan(self):
        client = APIClient()
        client.force_authenticate(user=UserFactory())

        data = client.get("/api/v1/banking/onboarding-summary").json()["data"]

        self.assertIsNone(data["detection"]["months_history"])
        assert_same_shape(self, data, OnboardingSummarySerializer())

    def test_import(self):
        response = self.client.post(
            f"/api/v1/banking/scans/{self.scan_id}/import",
            {"all": True},
            format="json",
        )

        self.assertEqual(response.status_code, 201)
        data = response.json()["data"]
        self.assertGreater(data["imported_count"], 0)
        assert_same_shape(self, data, ImportReportSerializer())

        again = self.client.post(
            f"/api/v1/banking/scans/{self.scan_id}/import",
            {"all": True},
            format="json",
        ).json()["data"]
        self.assertGreater(again["skipped_count"], 0)
        assert_same_shape(self, again, ImportReportSerializer())

    def test_onboarding_state_and_skip_bank(self):
        for body in (
            self.client.get("/api/v1/users/onboarding").json(),
            self.client.post("/api/v1/users/onboarding/skip-bank").json(),
        ):
            assert_same_shape(self, body["data"], OnboardingStateSerializer())
