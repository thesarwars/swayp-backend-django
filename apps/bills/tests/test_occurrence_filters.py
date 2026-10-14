"""Web §4: one bill's occurrences, search, and ordering."""

import datetime as dt

from django.test import TestCase
from rest_framework.test import APIClient

from apps.bills.factories import BillFactory, BillOccurrenceFactory
from apps.vendors.factories import UserFactory, VendorFactory

URL = "/api/v1/bills/occurrences"


class OccurrenceFilterTests(TestCase):

    def setUp(self):
        self.user = UserFactory()
        self.client = APIClient()
        self.client.force_authenticate(user=self.user)
        self.wework = BillFactory(
            user=self.user, vendor=VendorFactory(user=self.user, name="WeWork"))
        self.coned = BillFactory(
            user=self.user, vendor=VendorFactory(user=self.user, name="Con Edison"))
        BillOccurrenceFactory(bill=self.wework, due_date=dt.date(2027, 1, 1), amount="300.00")
        BillOccurrenceFactory(bill=self.wework, due_date=dt.date(2027, 2, 1), amount="100.00")
        BillOccurrenceFactory(bill=self.coned, due_date=dt.date(2027, 1, 15), amount="200.00")

    def ids(self, query):
        response = self.client.get(f"{URL}?{query}")
        self.assertEqual(response.status_code, 200, response.content)
        return response.json()["data"]

    def test_one_bill(self):
        rows = self.ids(f"bill={self.wework.id}")

        self.assertEqual({r["bill_id"] for r in rows}, {str(self.wework.id)})

    def test_search(self):
        rows = self.ids("search=edison")

        self.assertEqual([r["vendor_name"] for r in rows], ["Con Edison"])

    def test_ordering(self):
        amounts = [r["amount"] for r in self.ids("ordering=-amount&date_from=2027-01-01")]
        newest = [r["due_date"] for r in self.ids("ordering=-due_date&date_from=2027-01-01")]

        self.assertEqual(amounts, ["300.00", "200.00", "100.00"])
        self.assertEqual(newest, sorted(newest, reverse=True))

    def test_bad_values_are_400(self):
        for query, field in (("ordering=sideways", "ordering"),
                             ("bill=not-a-uuid", "bill")):
            with self.subTest(query=query):
                response = self.client.get(f"{URL}?{query}")
                self.assertEqual(response.status_code, 400)
                self.assertIn(field, response.json()["errors"])
