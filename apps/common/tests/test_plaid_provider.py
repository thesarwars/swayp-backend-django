"""The Plaid adapter, against a stubbed SDK.

Stubbed rather than live, because ``config/settings/test.py`` is explicit that
the suite has to run with nothing else running — an unrunnable suite is
indistinguishable from no suite. The live sandbox test lives at the bottom and
is skipped unless someone asks for it.

What is worth testing here is not "does it call Plaid" but the three places a
translation can silently lose meaning: the error codes that are not failures,
money that must not go through float, and the recurring-stream shape.
"""

import datetime as dt
from decimal import Decimal
from unittest import mock

from django.test import SimpleTestCase, override_settings

from integrations.bank_data.base import (
    BankDataNotReady,
    BankDataProviderError,
    BankReauthRequired,
)


class FakeApiException(Exception):
    """Stands in for plaid.ApiException, which carries its code in the body."""

    def __init__(self, body=""):
        super().__init__(body)
        self.body = body


def build_provider(**responses):
    """A provider whose client returns canned dicts.

    The SDK is replaced wholesale so no import of plaid is required to run
    this, and every call is recorded for assertion.
    """
    from integrations.bank_data.plaid import PlaidBankDataProvider

    provider = PlaidBankDataProvider.__new__(PlaidBankDataProvider)

    fake_plaid = mock.Mock()
    fake_plaid.ApiException = FakeApiException

    provider._plaid = fake_plaid
    provider._client = mock.Mock(**responses)

    return provider


def error(code):
    return FakeApiException(body=f'{{"error_code": "{code}"}}')


class ErrorTranslationTests(SimpleTestCase):
    """The codes that must not be flattened into one 500."""

    def call_raising(self, exc):
        provider = build_provider()

        def boom(_request):
            raise exc

        return provider, boom

    def test_login_required_is_not_a_fault(self):
        """A changed bank password is the user's to fix, nobody else's."""
        provider, boom = self.call_raising(error("ITEM_LOGIN_REQUIRED"))

        with self.assertRaises(BankReauthRequired):
            provider._call(boom, None)

    def test_product_not_ready_is_not_a_failure(self):
        """The first scan after linking routinely arrives before the data.

        Reported as a generic error it would mark every user's first scan
        FAILED, which is the whole reason this code has a type of its own.
        """
        provider, boom = self.call_raising(error("PRODUCT_NOT_READY"))

        with self.assertRaises(BankDataNotReady):
            provider._call(boom, None)

    def test_anything_else_is_a_provider_error(self):
        provider, boom = self.call_raising(error("INTERNAL_SERVER_ERROR"))

        with self.assertRaises(BankDataProviderError) as ctx:
            provider._call(boom, None)

        self.assertNotIsInstance(ctx.exception, BankReauthRequired)
        self.assertNotIsInstance(ctx.exception, BankDataNotReady)

    def test_an_unparseable_body_still_raises(self):
        """A malformed error must not become a KeyError further up."""
        provider, boom = self.call_raising(FakeApiException(body="not json"))

        with self.assertRaises(BankDataProviderError):
            provider._call(boom, None)


class TransactionMappingTests(SimpleTestCase):

    def response(self, rows, total=None):
        return {
            "transactions": rows,
            "total_transactions": total if total is not None else len(rows),
        }

    def test_amounts_are_decimal_not_float(self):
        """These become bill amounts. Decimal(0.1) is not 0.1."""
        provider = build_provider(
            transactions_get=mock.Mock(
                return_value=self.response(
                    [
                        {
                            "transaction_id": "t1",
                            "date": dt.date(2026, 5, 1),
                            "name": "WeWork",
                            "amount": 3200.10,
                        }
                    ]
                )
            )
        )

        txn = provider.get_transactions(access_token="a", months=1)[0]

        self.assertIsInstance(txn.amount, Decimal)
        self.assertEqual(txn.amount, Decimal("3200.1"))

    def test_merchant_name_wins_over_the_raw_descriptor(self):
        """"WeWork" clusters; "SQ *WEWORK 4821 NY" does not."""
        provider = build_provider(
            transactions_get=mock.Mock(
                return_value=self.response(
                    [
                        {
                            "transaction_id": "t1",
                            "date": dt.date(2026, 5, 1),
                            "name": "SQ *WEWORK 4821 NY",
                            "merchant_name": "WeWork",
                            "amount": 10,
                        }
                    ]
                )
            )
        )

        self.assertEqual(
            provider.get_transactions(access_token="a")[0].name, "WeWork"
        )

    def test_it_pages_past_the_first_five_hundred(self):
        """A year of a busy account runs past one page.

        Without paging the bills beyond it are never detected, and nothing
        anywhere reports a problem.
        """
        page_one = self.response(
            [
                {
                    "transaction_id": f"t{i}",
                    "date": dt.date(2026, 5, 1),
                    "name": "x",
                    "amount": 1,
                }
                for i in range(500)
            ],
            total=501,
        )
        page_two = self.response(
            [
                {
                    "transaction_id": "t500",
                    "date": dt.date(2026, 5, 1),
                    "name": "x",
                    "amount": 1,
                }
            ],
            total=501,
        )

        provider = build_provider(
            transactions_get=mock.Mock(side_effect=[page_one, page_two])
        )

        self.assertEqual(len(provider.get_transactions(access_token="a")), 501)

    def test_an_empty_page_stops_the_loop(self):
        """A total that never matches must not spin forever."""
        provider = build_provider(
            transactions_get=mock.Mock(return_value=self.response([], total=99))
        )

        self.assertEqual(provider.get_transactions(access_token="a"), ())


class RecurringMappingTests(SimpleTestCase):

    def stream(self, **overrides):
        base = {
            "merchant_name": "Verizon Business",
            "average_amount": {"amount": 389.00},
            "frequency": "MONTHLY",
            "last_date": dt.date(2026, 5, 15),
            "transaction_ids": ["a", "b", "c"],
        }
        base.update(overrides)

        return base

    def provider_returning(self, *streams, inflow=()):
        return build_provider(
            transactions_recurring_get=mock.Mock(
                return_value={
                    "outflow_streams": list(streams),
                    "inflow_streams": list(inflow),
                }
            )
        )

    def test_a_stream_becomes_a_candidate(self):
        provider = self.provider_returning(self.stream())

        candidate = provider.get_recurring(access_token="a")[0]

        self.assertEqual(candidate.vendor_name, "Verizon Business")
        self.assertEqual(candidate.amount, Decimal("389.0"))
        self.assertEqual(candidate.cadence, "MONTHLY")
        self.assertEqual(candidate.due_day, 15)
        self.assertEqual(candidate.occurrences, 3)

    def test_inflows_are_ignored(self):
        """Money arriving is not a bill."""
        provider = self.provider_returning(
            self.stream(), inflow=[self.stream(merchant_name="Payroll")]
        )

        candidates = provider.get_recurring(access_token="a")

        self.assertEqual(len(candidates), 1)
        self.assertEqual(candidates[0].vendor_name, "Verizon Business")

    def test_an_unknown_frequency_falls_back_rather_than_dropping(self):
        """A wrong cadence is a correction on the review screen. A dropped
        candidate is invisible."""
        provider = self.provider_returning(
            self.stream(frequency="UNKNOWN")
        )

        self.assertEqual(
            provider.get_recurring(access_token="a")[0].cadence, "MONTHLY"
        )

    def test_a_stream_with_no_merchant_falls_back_to_the_description(self):
        provider = self.provider_returning(
            self.stream(merchant_name=None, description="ACH DEBIT CONED")
        )

        self.assertEqual(
            provider.get_recurring(access_token="a")[0].vendor_name,
            "ACH DEBIT CONED",
        )

    def test_a_stream_with_no_last_date_still_maps(self):
        provider = self.provider_returning(self.stream(last_date=None))

        self.assertEqual(provider.get_recurring(access_token="a")[0].due_day, 1)


class BalanceTests(SimpleTestCase):

    def provider_with(self, balances):
        return build_provider(
            accounts_balance_get=mock.Mock(
                return_value={
                    "accounts": [
                        {"account_id": "acc-1", "balances": balances}
                    ]
                }
            )
        )

    def test_available_is_preferred_over_current(self):
        """current includes pending, which is not spendable."""
        provider = self.provider_with({"available": 900.50, "current": 1200})

        self.assertEqual(
            provider.get_balance(access_token="a", account_id="acc-1"),
            Decimal("900.5"),
        )

    def test_it_falls_back_to_current_rather_than_reporting_zero(self):
        """Some accounts have no available balance. Zero reads as empty."""
        provider = self.provider_with({"available": None, "current": 1200})

        self.assertEqual(
            provider.get_balance(access_token="a", account_id="acc-1"),
            Decimal("1200"),
        )

    def test_an_unknown_account_is_an_error_not_a_zero(self):
        provider = self.provider_with({"available": 1})

        with self.assertRaises(BankDataProviderError):
            provider.get_balance(access_token="a", account_id="nope")


class ExchangeTests(SimpleTestCase):

    def build(self, institution_side_effect=None):
        provider = build_provider(
            item_public_token_exchange=mock.Mock(
                return_value={"access_token": "acc-tok", "item_id": "item-1"}
            ),
            accounts_get=mock.Mock(
                return_value={
                    "accounts": [
                        {
                            "account_id": "a1",
                            "mask": "4821",
                            "name": "Business Checking",
                            "type": "depository",
                            "subtype": "checking",
                            "balances": {"current": 41200},
                        }
                    ],
                    "item": {"institution_id": "ins_1"},
                }
            ),
            institutions_get_by_id=(
                mock.Mock(side_effect=institution_side_effect)
                if institution_side_effect
                else mock.Mock(
                    return_value={"institution": {"name": "Chase Bank"}}
                )
            ),
        )

        return provider

    def test_subtype_is_used_as_the_account_type(self):
        """The app keys on "checking"; Plaid's type says "depository"."""
        result = self.build().exchange_public_token(public_token="p")

        self.assertEqual(result.accounts[0].type, "checking")
        self.assertEqual(result.accounts[0].mask, "4821")

    def test_the_institution_name_is_fetched_not_taken_from_the_client(self):
        result = self.build().exchange_public_token(public_token="p")

        self.assertEqual(result.institution_name, "Chase Bank")

    def test_a_failed_institution_lookup_does_not_lose_the_connection(self):
        """The user has already authorised by this point.

        Refusing here would strand an access token they granted and Swayp
        never stored — the link would have to be done again for a cosmetic
        field.
        """
        provider = self.build(
            institution_side_effect=error("INSTITUTION_NOT_RESPONDING")
        )

        result = provider.exchange_public_token(public_token="p")

        self.assertEqual(result.institution_name, "")
        self.assertEqual(result.access_token, "acc-tok")


@override_settings(PLAID_CLIENT_ID="", PLAID_SECRET="")
class ConfigurationTests(SimpleTestCase):

    def test_it_refuses_to_build_without_keys(self):
        """With a message that names the way out."""
        from integrations.bank_data.plaid import PlaidBankDataProvider

        with self.assertRaises(BankDataProviderError) as ctx:
            PlaidBankDataProvider()

        self.assertIn("BANK_DATA_PROVIDER=mock", str(ctx.exception))

    @override_settings(PLAID_CLIENT_ID="id", PLAID_SECRET="s", PLAID_ENV="dev")
    def test_it_refuses_an_environment_plaid_does_not_have(self):
        """"development" was retired by Plaid; failing at boot beats failing
        at the first bank connection."""
        from integrations.bank_data.plaid import PlaidBankDataProvider

        with self.assertRaises(BankDataProviderError) as ctx:
            PlaidBankDataProvider()

        self.assertIn("PLAID_ENV", str(ctx.exception))


class SandboxTests(SimpleTestCase):
    """The real thing, skipped unless asked for.

    Run with ``PLAID_SANDBOX_TESTS=1`` and sandbox keys in the environment.
    This is the test that would have caught PRODUCT_NOT_READY on day one
    instead of on the first real user's first connection.
    """

    databases = set()

    def setUp(self):
        import os

        if not os.environ.get("PLAID_SANDBOX_TESTS"):
            self.skipTest("set PLAID_SANDBOX_TESTS=1 to run against Plaid")

    def test_the_whole_read_path_works(self):
        import requests
        from django.conf import settings

        from integrations.bank_data.plaid import PlaidBankDataProvider

        provider = PlaidBankDataProvider()

        token = provider.create_link_token(user_ref="sandbox-test")
        self.assertTrue(token.token.startswith("link-sandbox-"))

        public_token = requests.post(
            "https://sandbox.plaid.com/sandbox/public_token/create",
            json={
                "client_id": settings.PLAID_CLIENT_ID,
                "secret": settings.PLAID_SECRET,
                "institution_id": "ins_109508",
                "initial_products": ["transactions"],
            },
            timeout=30,
        ).json()["public_token"]

        result = provider.exchange_public_token(public_token=public_token)

        self.assertTrue(result.access_token)
        self.assertTrue(result.accounts)
        self.assertEqual(result.institution_name, "First Platypus Bank")

        try:
            provider.get_balance(
                access_token=result.access_token,
                account_id=result.accounts[0].account_id,
            )
        finally:
            provider.remove_item(access_token=result.access_token)


@override_settings(
    PLAID_REDIRECT_URI="https://app.swayp.test/plaid/oauth",
    PLAID_ANDROID_PACKAGE_NAME="com.swayp.app",
    PLAID_WEBHOOK_URL="https://api.swayp.test/webhooks/plaid",
)
class LinkTokenPlatformTests(SimpleTestCase):
    """BANK-5: an OAuth bank hands the user back by package on Android and by
    redirect URI elsewhere. Plaid takes one or the other, never both."""

    def sent(self, platform):
        provider = build_provider(
            link_token_create=mock.Mock(
                return_value={
                    "link_token": "link-sandbox-1",
                    "expiration": "2026-10-10T12:00:00Z",
                }
            )
        )

        token = provider.create_link_token(user_ref="u1", platform=platform)
        request = provider._client.link_token_create.call_args[0][0]

        return token, request.to_dict()

    def test_android_sends_the_package_and_no_redirect(self):
        _, body = self.sent("android")

        self.assertEqual(body["android_package_name"], "com.swayp.app")
        self.assertNotIn("redirect_uri", body)

    def test_ios_web_and_unset_send_the_redirect_and_no_package(self):
        for platform in ("ios", "web", None):
            with self.subTest(platform=platform):
                _, body = self.sent(platform)

                self.assertEqual(
                    body["redirect_uri"], "https://app.swayp.test/plaid/oauth"
                )
                self.assertNotIn("android_package_name", body)

    @override_settings(PLAID_ANDROID_PACKAGE_NAME="")
    def test_an_unset_package_is_omitted_not_sent_empty(self):
        _, body = self.sent("android")

        self.assertNotIn("android_package_name", body)
        self.assertNotIn("redirect_uri", body)

    def test_expiration_is_passed_through(self):
        token, _ = self.sent("ios")

        self.assertEqual(token.expiration, "2026-10-10T12:00:00Z")
