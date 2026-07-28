"""Balance freshness (E5 -> E7).

``available_balance`` used to be written once, at link time, and read forever
after as if it were current.
"""

import datetime as dt
from decimal import Decimal
from unittest import mock

from django.test import TestCase, override_settings
from django.utils import timezone

from apps.banking.factories import BankAccountFactory
from apps.banking.models import BankConnectionStatus
from apps.banking.services.balance_service import BalanceService


class _Boom:
    """A provider that is down."""

    name = "boom"

    def get_balance(self, *, access_token, account_id):
        raise RuntimeError("provider unavailable")


@override_settings(BALANCE_MAX_AGE_SECONDS=300)
class BalanceServiceTests(TestCase):

    def _account(self, **kwargs):
        kwargs.setdefault("available_balance", Decimal("100.00"))
        return BankAccountFactory(**kwargs)

    def test_stale_balance_is_refreshed_from_the_provider(self):
        account = self._account(
            balance_as_of=timezone.now() - dt.timedelta(hours=2)
        )

        BalanceService().refresh(account)
        account.refresh_from_db()

        # The mock provider reports 41200.00.
        self.assertEqual(account.available_balance, Decimal("41200.00"))
        self.assertTrue(BalanceService.is_fresh(account))

    def test_never_synced_balance_is_refreshed(self):
        account = self._account(available_balance=None, balance_as_of=None)

        BalanceService().refresh(account)
        account.refresh_from_db()

        self.assertEqual(account.available_balance, Decimal("41200.00"))

    def test_fresh_balance_is_not_refetched(self):
        account = self._account(balance_as_of=timezone.now())

        service = BalanceService()
        with mock.patch.object(service, "provider", _Boom()):
            service.refresh(account)

        account.refresh_from_db()
        self.assertEqual(account.available_balance, Decimal("100.00"))

    def test_force_refetches_a_fresh_balance(self):
        account = self._account(balance_as_of=timezone.now())

        BalanceService().refresh(account, force=True)
        account.refresh_from_db()

        self.assertEqual(account.available_balance, Decimal("41200.00"))

    def test_provider_failure_leaves_the_stored_balance_alone(self):
        stamp = timezone.now() - dt.timedelta(hours=2)
        account = self._account(balance_as_of=stamp)

        service = BalanceService()
        with mock.patch.object(service, "provider", _Boom()):
            service.refresh(account)

        account.refresh_from_db()
        self.assertEqual(account.available_balance, Decimal("100.00"))
        # The stamp still says how old it is, so callers can caveat it.
        self.assertEqual(account.balance_as_of, stamp)

    def test_inactive_connection_is_not_asked(self):
        account = self._account(
            balance_as_of=None,
            connection__status=BankConnectionStatus.DISCONNECTED,
        )

        service = BalanceService()
        with mock.patch.object(service, "provider", _Boom()):
            service.refresh(account)

        account.refresh_from_db()
        self.assertEqual(account.available_balance, Decimal("100.00"))
