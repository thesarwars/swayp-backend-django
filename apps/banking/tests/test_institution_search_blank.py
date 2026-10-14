"""Web B1: a blank institution search answers an empty list, never 500,
and never reaches the provider."""

from unittest import mock

from django.test import TestCase
from rest_framework.test import APIClient

from apps.vendors.factories import UserFactory


class BlankSearchTests(TestCase):

    def test_missing_or_blank_search_is_an_empty_list(self):
        client = APIClient()
        client.force_authenticate(user=UserFactory())

        with mock.patch(
            "apps.banking.services.link_service.BankLinkService."
            "search_institutions"
        ) as search:
            for url in ("/api/v1/banking/institutions",
                        "/api/v1/banking/institutions?search=",
                        "/api/v1/banking/institutions?search=%20%20"):
                with self.subTest(url=url):
                    response = client.get(url)
                    self.assertEqual(response.status_code, 200)
                    self.assertEqual(response.json()["data"], [])

        search.assert_not_called()
