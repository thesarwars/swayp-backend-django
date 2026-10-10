"""DASH-7 follow-up: a page past the end is empty on every paged list.

The service-paged lists returned the last page again and the DRF-paged
ones answered 404. Both now return an empty list with hasNext false.
"""

from django.test import TestCase
from rest_framework.test import APIClient

from apps.vendors.factories import UserFactory


class PastTheEndTests(TestCase):

    def setUp(self):
        self.client = APIClient()
        self.client.force_authenticate(user=UserFactory())

    def test_drf_paged_list_answers_an_empty_page(self):
        response = self.client.get("/api/v1/bills/occurrences?page=9")

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["data"], [])
        self.assertFalse(body["pagination"]["hasNext"])
        self.assertEqual(body["pagination"]["page"], 9)

    def test_service_paged_list_answers_an_empty_page(self):
        response = self.client.get("/api/v1/notifications?page=9")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["data"], [])

    def test_a_non_numeric_page_is_still_rejected(self):
        response = self.client.get("/api/v1/bills/occurrences?page=abc")

        self.assertEqual(response.status_code, 404)
