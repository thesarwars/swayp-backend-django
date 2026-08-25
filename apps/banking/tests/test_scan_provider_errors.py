"""A scan tells the two provider conditions apart from a real failure.

Both were caught against the Plaid sandbox rather than reasoned about, and
both used to land in the same ``except Exception`` that marks a scan FAILED:

* ``PRODUCT_NOT_READY`` — Plaid pulls an item's history asynchronously, so the
  first scan of a new connection asks before the data has arrived. That is
  every user's onboarding, and marking it FAILED would put an error screen at
  the end of the happy path.
* ``ITEM_LOGIN_REQUIRED`` — the user changed their bank password. The scan is
  not what broke, and recording it on the scan alone leaves the connection
  looking healthy while every later scan fails the same way.
"""

from unittest import mock

from django.test import TestCase

from apps.banking.factories import (
    BankConnectionFactory,
    TransactionScanFactory,
)
from apps.banking.models import BankConnectionStatus
from apps.banking.services.scan_service import ScanService
from apps.common.enums import ScanStatus
from integrations.bank_data.base import (
    BankDataNotReady,
    BankDataProviderError,
    BankReauthRequired,
)


class ScanProviderErrorTests(TestCase):

    def setUp(self):
        self.connection = BankConnectionFactory()
        self.scan = TransactionScanFactory(
            connection=self.connection, status=ScanStatus.RUNNING
        )

    def run_scan_raising(self, exc):
        service = ScanService()
        service.provider = mock.Mock()
        service.provider.get_transactions.side_effect = exc

        return service.run(self.scan)

    def test_not_ready_leaves_the_scan_running(self):
        """So the progress screen keeps waiting and a retry completes it."""
        self.run_scan_raising(BankDataNotReady("PRODUCT_NOT_READY"))
        self.scan.refresh_from_db()

        self.assertEqual(self.scan.status, ScanStatus.RUNNING)
        self.assertEqual(self.scan.error_message, "")
        self.assertIsNone(self.scan.completed_at)

    def test_not_ready_does_not_break_the_connection(self):
        self.run_scan_raising(BankDataNotReady("PRODUCT_NOT_READY"))
        self.connection.refresh_from_db()

        self.assertEqual(self.connection.status, BankConnectionStatus.ACTIVE)

    def test_reauth_marks_the_connection_not_just_the_scan(self):
        self.run_scan_raising(BankReauthRequired("ITEM_LOGIN_REQUIRED"))

        self.scan.refresh_from_db()
        self.connection.refresh_from_db()

        self.assertEqual(self.scan.status, ScanStatus.FAILED)
        self.assertEqual(self.connection.status, BankConnectionStatus.ERROR)

    def test_the_reauth_message_is_addressed_to_the_user(self):
        """They are the only one who can fix it, so it must not be a code."""
        self.run_scan_raising(BankReauthRequired("ITEM_LOGIN_REQUIRED"))
        self.scan.refresh_from_db()

        self.assertIn("sign in again", self.scan.error_message)
        self.assertNotIn("ITEM_LOGIN_REQUIRED", self.scan.error_message)

    def test_a_real_failure_still_fails(self):
        """The new branches must not swallow the case they were carved from."""
        with self.assertRaises(BankDataProviderError):
            self.run_scan_raising(BankDataProviderError("INTERNAL"))

        self.scan.refresh_from_db()

        self.assertEqual(self.scan.status, ScanStatus.FAILED)
        self.assertIn("INTERNAL", self.scan.error_message)
