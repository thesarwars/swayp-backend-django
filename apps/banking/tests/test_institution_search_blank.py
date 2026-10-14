"""Web B1: a blank institution search never reaches Plaid (which refuses
it, and the error surfaced as a 500)."""

from unittest import mock

from django.test import SimpleTestCase, TestCase
from rest_framework.test import APIClient

from apps.vendors.factories import UserFactory


class PlaidBlankQueryTests(SimpleTestCase):

    def test_a_blank_query_returns_nothing_without_calling_plaid(self):
        from integrations.bank_data.plaid import PlaidBankDataProvider

        provider = PlaidBankDataProvider.__new__(PlaidBankDataProvider)
        provider._call = mock.Mock()

        for query in ("", "   "):
            with self.subTest(query=query):
                self.assertEqual(provider.search_institutions(query=query), ())

        provider._call.assert_not_called()


class BlankSearchEndpointTests(TestCase):

    def test_missing_search_is_never_a_500(self):
        client = APIClient()
        client.force_authenticate(user=UserFactory())

        for url in ("/api/v1/banking/institutions",
                    "/api/v1/banking/institutions?search="):
            with self.subTest(url=url):
                self.assertEqual(client.get(url).status_code, 200)


class LinkTokenExpirationTests(SimpleTestCase):
    """Web B8: expiration is ISO-8601, not Python's str(datetime)."""

    def test_iso(self):
        import datetime as dt

        from integrations.bank_data.plaid import _iso

        value = dt.datetime(2026, 10, 14, 10, 15, 16, tzinfo=dt.timezone.utc)

        self.assertEqual(_iso(value), "2026-10-14T10:15:16Z")
        self.assertIsNone(_iso(None))
        self.assertEqual(_iso("2026-10-14T10:15:16Z"), "2026-10-14T10:15:16Z")
