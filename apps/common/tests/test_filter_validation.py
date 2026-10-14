"""Web B3: an unknown filter value is a 400, not a filter quietly dropped
(which answered the unfiltered list as if it were the filtered one)."""

from django.test import TestCase
from rest_framework.test import APIClient

from apps.vendors.factories import UserFactory


class FilterValidationTests(TestCase):

    def setUp(self):
        self.client = APIClient()
        self.client.force_authenticate(user=UserFactory())

    def test_unknown_values_are_400(self):
        for url, field in [
            ("/api/v1/vendors?rail=BOGUS", "rail"),
            ("/api/v1/vendors?status=BOGUS", "status"),
            ("/api/v1/vendors?category=not-a-uuid", "category"),
            ("/api/v1/vendors/summary?rail=BOGUS", "rail"),
            ("/api/v1/bills/occurrences?status=BOGUS", "status"),
            ("/api/v1/bills/occurrences?status=DUE,BOGUS", "status"),
            ("/api/v1/bills/occurrences?date_from=bad", "date_from"),
            ("/api/v1/payments/history?status=BOGUS", "status"),
        ]:
            with self.subTest(url=url):
                response = self.client.get(url)

                self.assertEqual(response.status_code, 400)
                self.assertIn(field, response.json()["errors"])

    def test_valid_values_still_work(self):
        for url in [
            "/api/v1/vendors?rail=ach",
            "/api/v1/vendors?status=DELETED",
            "/api/v1/bills/occurrences?status=OVERDUE,DUE",
            "/api/v1/bills/occurrences?date_from=2026-01-01",
            "/api/v1/payments/history?status=SUCCESSFUL",
        ]:
            with self.subTest(url=url):
                self.assertEqual(self.client.get(url).status_code, 200)
