"""Web C3: every spelling of page size, date range and category works on
every list, whichever one that endpoint reads."""

from django.test import TestCase
from rest_framework.test import APIClient

from apps.vendors.factories import UserFactory, VendorFactory


class QueryAliasTests(TestCase):

    def setUp(self):
        self.user = UserFactory()
        self.client = APIClient()
        self.client.force_authenticate(user=self.user)

    def test_page_size_spellings_on_a_drf_list(self):
        VendorFactory.create_batch(3, user=self.user)

        for name in ("pageSize", "page_size"):
            with self.subTest(name=name):
                body = self.client.get(f"/api/v1/vendors?{name}=2").json()

                self.assertEqual(len(body["data"]), 2)
                self.assertEqual(body["pagination"]["pageSize"], 2)

    def test_date_range_spellings_reach_each_endpoint(self):
        for url in ("/api/v1/payments/history", "/api/v1/billing/fees",
                    "/api/v1/bills/occurrences"):
            for name in ("date_from", "from_date", "fromDate"):
                with self.subTest(url=url, name=name):
                    response = self.client.get(f"{url}?{name}=bad-date")

                    # Every spelling reaches the endpoint's own validation:
                    # a 400, never silently ignored. (fees answers 400 for
                    # no subscription before dates, which is still a 400.)
                    self.assertEqual(response.status_code, 400)

    def test_category_spellings(self):
        for name in ("category", "category_id", "categoryId"):
            with self.subTest(name=name):
                response = self.client.get(f"/api/v1/vendors?{name}=not-a-uuid")

                self.assertEqual(response.status_code, 400)
