"""Factories build valid rows, and scan progress is observable (E5-S1 / S4)."""

from django.db import transaction
from django.test import TestCase, TransactionTestCase, override_settings

from apps.banking.models import (
    BankAccount,
    BankConnection,
    BillDetectionCandidate,
    TransactionScan,
)
from apps.banking.factories import (
    BankAccountFactory,
    BankConnectionFactory,
    BillDetectionCandidateFactory,
    TransactionScanFactory,
)
from apps.bills.models.bill import Bill
from apps.bills.models.bill_occurrence import BillOccurrence
from apps.bills.models.standing_authorization import StandingAuthorization
from apps.bills.factories import (
    BillFactory,
    BillOccurrenceFactory,
    StandingAuthorizationFactory,
)
from apps.vendors.models import Vendor, VendorPaymentMethod
from apps.vendors.factories import (
    VendorFactory,
    VendorPaymentMethodFactory,
)


class FactoryTests(TestCase):

    def test_banking_factories_build_valid_rows(self):
        BankAccountFactory()

        self.assertEqual(BankConnection.objects.count(), 1)
        self.assertEqual(BankAccount.objects.count(), 1)

    def test_connection_factory_encrypts_the_token(self):
        BankConnectionFactory()

        from django.db import connection as db

        with db.cursor() as cursor:
            cursor.execute("SELECT access_token FROM bank_connections")
            stored = cursor.fetchone()[0]

        self.assertNotIn("mock-access-token", stored)

    def test_candidate_factory(self):
        BillDetectionCandidateFactory()

        self.assertEqual(BillDetectionCandidate.objects.count(), 1)
        self.assertEqual(TransactionScan.objects.count(), 1)

    def test_scan_factory(self):
        scan = TransactionScanFactory(detected_count=4)

        self.assertEqual(scan.detected_count, 4)

    def test_vendor_factories_cover_all_three_branches(self):
        ach = VendorPaymentMethodFactory()
        network = VendorPaymentMethodFactory(network=True, is_primary=False)
        check = VendorPaymentMethodFactory(check=True, is_primary=False)

        self.assertEqual(ach.method_type, "ACH")
        self.assertEqual(network.method_type, "NETWORK")
        self.assertEqual(check.method_type, "CHECK")

        # Each branch must satisfy the model's own validation.
        for method in (ach, network, check):
            with self.subTest(method=method.method_type):
                method.full_clean(exclude=["vendor"])

    def test_vendor_factory_makes_distinct_vendors(self):
        VendorFactory()
        VendorFactory()

        self.assertEqual(Vendor.objects.count(), 2)
        self.assertEqual(
            Vendor.objects.values("name").distinct().count(), 2
        )

    def test_bill_factory_shares_the_user_with_its_vendor(self):
        bill = BillFactory()

        self.assertEqual(bill.user_id, bill.vendor.user_id)
        bill.full_clean()

    def test_occurrence_and_authorization_factories(self):
        BillOccurrenceFactory()
        StandingAuthorizationFactory()

        self.assertEqual(Bill.objects.count(), 2)
        self.assertEqual(BillOccurrence.objects.count(), 1)
        self.assertEqual(StandingAuthorization.objects.count(), 1)
        self.assertIsNone(StandingAuthorization.objects.get().revoked_at)

    def test_no_raw_bank_numbers_reach_any_factory_row(self):
        VendorPaymentMethodFactory()

        row = VendorPaymentMethod.objects.get()
        self.assertEqual(row.account_last4, "8837")
        self.assertFalse(hasattr(row, "account_number"))
        self.assertFalse(hasattr(row, "routing_number"))


@override_settings(BANK_DATA_PROVIDER="mock")
class ScanProgressVisibilityTests(TransactionTestCase):
    """E5-S4: "progress observable mid-scan".

    TransactionTestCase, not TestCase — the point is what other connections
    can see, which a test-wide transaction would hide.
    """

    reset_sequences = True

    def test_run_is_not_wrapped_in_one_transaction(self):
        """Intermediate writes must land, not sit invisible until the end."""
        from apps.banking.services.scan_service import ScanService

        connection = BankConnectionFactory()
        scan = TransactionScan.objects.create(
            connection=connection, months_history=12
        )

        observed = []

        original = TransactionScan.save

        def spy(self, *args, **kwargs):
            result = original(self, *args, **kwargs)
            # in_atomic_block would be True if run() held one big transaction.
            observed.append(transaction.get_connection().in_atomic_block)
            return result

        TransactionScan.save = spy
        try:
            ScanService().run(scan)
        finally:
            TransactionScan.save = original

        self.assertTrue(observed, "expected progress writes during the scan")
        self.assertFalse(
            any(observed),
            msg=(
                "progress saves ran inside an open transaction, so a poller "
                "would not see the count climb"
            ),
        )

    def test_progress_counts_reach_the_database_as_the_scan_runs(self):
        from apps.banking.services.scan_service import ScanService

        connection = BankConnectionFactory()
        scan = TransactionScan.objects.create(
            connection=connection, months_history=12
        )

        seen = []
        original = TransactionScan.save

        def spy(self, *args, **kwargs):
            result = original(self, *args, **kwargs)
            # Re-read through a fresh query, as a poller would.
            seen.append(
                TransactionScan.objects.only("detected_count")
                .get(pk=self.pk)
                .detected_count
            )
            return result

        TransactionScan.save = spy
        try:
            ScanService().run(scan)
        finally:
            TransactionScan.save = original

        # The count climbs rather than jumping straight to the total.
        self.assertEqual(sorted(set(seen)), [0, 1, 2, 3, 4])
