"""Bank link, scan, detection and import (E5-S1 … E5-S6)."""

import datetime as dt
from decimal import Decimal

from django.test import TestCase, override_settings
from django.utils import timezone
from rest_framework.test import APIClient

from apps.banking.models import (
    BankAccount,
    BankConnection,
    BankConnectionStatus,
    BillDetectionCandidate,
    TransactionScan,
)
from apps.banking.services.import_service import BillImportService
from apps.banking.services.recurring_detector import (
    detect,
    infer_cadence,
    normalize_vendor,
)
from apps.bill_categories.models import BillCategory
from apps.bills.models.bill import Bill
from apps.common.enums import (
    BillFrequency,
    BillSource,
    PaymentStatus,
    ScanStatus,
    VendorSource,
)
from apps.payments.models import Payment
from apps.providers.models import Provider
from apps.users.models import User
from apps.vendors.models import Vendor
from integrations.bank_data.mock import MockBankDataProvider

D = dt.date


class Tx:
    """Minimal transaction stand-in for detector tests."""

    def __init__(self, name, amount, posted_on):
        self.name = name
        self.amount = Decimal(amount)
        self.posted_on = posted_on


def monthly(name, amount, day, count, start_year=2026, start_month=1):
    out = []
    year, month = start_year, start_month
    for _ in range(count):
        out.append(Tx(name, amount, D(year, month, day)))
        month += 1
        if month > 12:
            month = 1
            year += 1
    return out


class NormalisationTests(TestCase):

    def test_bank_descriptor_noise_is_stripped(self):
        cases = [
            ("POS DEBIT WEWORK #1123 07/01", "wework"),
            ("WeWork", "wework"),
            ("ACH PMT VERIZON BUSINESS REF 88", "verizon business"),
            ("Verizon Business", "verizon business"),
            ("RECURRING PAYMENT AMAZON WEB SERVICES", "amazon web services"),
        ]

        for raw, expected in cases:
            with self.subTest(raw=raw):
                self.assertEqual(normalize_vendor(raw), expected)

    def test_empty_and_numeric_names_normalise_to_nothing(self):
        for raw in ["", "   ", "12345", "### ---"]:
            with self.subTest(raw=raw):
                self.assertEqual(normalize_vendor(raw), "")


class CadenceTests(TestCase):

    def test_cadence_inference(self):
        cases = [
            ([D(2026, 1, 5), D(2026, 1, 12), D(2026, 1, 19)],
             BillFrequency.WEEKLY),
            ([D(2026, 1, 1), D(2026, 2, 1), D(2026, 3, 1)],
             BillFrequency.MONTHLY),
            ([D(2026, 1, 1), D(2026, 4, 1), D(2026, 7, 1)],
             BillFrequency.QUARTERLY),
        ]

        for dates, expected in cases:
            with self.subTest(expected=expected):
                self.assertEqual(infer_cadence(dates)[0], expected)

    def test_irregular_intervals_are_rejected(self):
        self.assertIsNone(
            infer_cadence([D(2026, 1, 1), D(2026, 1, 6), D(2026, 5, 2)])
        )

    def test_a_single_date_has_no_cadence(self):
        self.assertIsNone(infer_cadence([D(2026, 1, 1)]))


class DetectionTests(TestCase):
    """Golden tests — same fixtures must always give the same candidates."""

    def test_three_occurrences_qualify(self):
        candidates = detect(monthly("WeWork", "3200.00", 1, 3))

        self.assertEqual(len(candidates), 1)
        self.assertEqual(candidates[0]["occurrences"], 3)

    def test_two_occurrences_are_rejected(self):
        self.assertEqual(detect(monthly("WeWork", "3200.00", 1, 2)), [])

    def test_one_off_purchases_are_ignored(self):
        transactions = [
            Tx("Staples", "122.45", D(2026, 3, 4)),
            Tx("Delta Air Lines", "845.20", D(2026, 4, 19)),
            Tx("Apple Store", "2399.00", D(2026, 5, 27)),
        ]

        self.assertEqual(detect(transactions), [])

    def test_amounts_within_tolerance_still_cluster(self):
        transactions = [
            Tx("Con Edison", "214.00", D(2026, 1, 22)),
            Tx("Con Edison", "218.40", D(2026, 2, 22)),
            Tx("Con Edison", "209.75", D(2026, 3, 22)),
        ]

        candidates = detect(transactions)

        self.assertEqual(len(candidates), 1)
        self.assertEqual(candidates[0]["occurrences"], 3)

    def test_one_vendor_can_yield_two_bills(self):
        """A $20 licence and a $3,200 rent are not one pattern."""
        transactions = (
            monthly("Acme", "20.00", 3, 4) + monthly("Acme", "3200.00", 18, 4)
        )

        candidates = detect(transactions)

        self.assertEqual(len(candidates), 2)
        self.assertEqual(
            sorted(str(c["amount"]) for c in candidates),
            ["20.00", "3200.00"],
        )

    def test_differently_spelled_descriptors_merge(self):
        transactions = [
            Tx("POS DEBIT WEWORK #1123", "3200.00", D(2026, 1, 1)),
            Tx("WeWork", "3200.00", D(2026, 2, 1)),
            Tx("ACH WEWORK PAYMENT", "3200.00", D(2026, 3, 1)),
        ]

        candidates = detect(transactions)

        self.assertEqual(len(candidates), 1)
        self.assertEqual(candidates[0]["occurrences"], 3)

    def test_the_mock_history_yields_the_expected_four(self):
        transactions = MockBankDataProvider().get_transactions(
            access_token="x", months=12
        )

        candidates = detect(transactions)
        names = sorted(c["vendor_name"] for c in candidates)

        self.assertEqual(
            names,
            ["Amazon Web Services", "Con Edison", "Verizon Business",
             "WeWork"],
        )
        # Two occurrences only — must not appear.
        self.assertNotIn("Blue Bottle Coffee", names)

    def test_candidates_are_ordered_by_confidence(self):
        candidates = detect(
            MockBankDataProvider().get_transactions(access_token="x")
        )
        counts = [c["occurrences"] for c in candidates]

        self.assertEqual(counts, sorted(counts, reverse=True))


@override_settings(BANK_DATA_PROVIDER="mock")
class OnboardingJourneyTests(TestCase):

    def setUp(self):
        self.user = User.objects.create_user(
            email="onboard@example.com", password="Sw@yp-Test-1"
        )
        BillCategory.objects.create(
            name="Commercial Rent", icon="https://e.com/i.png", color="#111"
        )
        BillCategory.objects.create(
            name="Other", icon="https://e.com/i.png", color="#222"
        )

        self.client = APIClient()
        self.client.force_authenticate(user=self.user)

    def link(self, public_token="public-mock-chase"):
        with self.captureOnCommitCallbacks(execute=True):
            return self.client.post(
                "/api/v1/banking/link/exchange",
                {"public_token": public_token, "consent_accepted": True},
                format="json",
            )

    def test_link_token_is_issued(self):
        response = self.client.post("/api/v1/banking/link/token")

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.data["data"]["link_token"])

    def test_exchange_without_consent_is_rejected(self):
        response = self.client.post(
            "/api/v1/banking/link/exchange",
            {"public_token": "public-mock-chase", "consent_accepted": False},
            format="json",
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(BankConnection.objects.count(), 0)

    def test_exchange_creates_connection_and_accounts(self):
        response = self.link()

        self.assertEqual(response.status_code, 201)
        connection = BankConnection.objects.get()
        self.assertEqual(connection.status, BankConnectionStatus.ACTIVE)
        self.assertEqual(connection.institution_name, "Chase Bank")
        self.assertIsNotNone(connection.consented_at)
        self.assertEqual(connection.accounts.count(), 2)

    def test_a_checking_account_becomes_the_funding_source(self):
        self.link()

        default = BankAccount.objects.get(is_default_funding_source=True)
        self.assertEqual(default.account_type, "CHECKING")

    def test_the_access_token_is_never_serialized(self):
        response = self.link()

        self.assertNotIn("access_token", response.data["data"])
        self.assertNotIn("mock-access-token", str(response.data))

    def test_the_access_token_is_encrypted_at_rest(self):
        self.link()

        from django.db import connection as db

        with db.cursor() as cursor:
            cursor.execute("SELECT access_token FROM bank_connections")
            stored = cursor.fetchone()[0]

        self.assertNotIn("mock-access-token", stored)
        # But the ORM still round-trips it.
        self.assertTrue(
            BankConnection.objects.get().access_token.startswith("mock-")
        )

    def test_a_different_institution_can_be_linked(self):
        self.link("public-mock-bofa")

        self.assertEqual(
            BankConnection.objects.get().institution_name,
            "Bank of America",
        )

    def test_exchange_starts_a_scan_that_detects_bills(self):
        response = self.link()

        scan = TransactionScan.objects.get()
        self.assertEqual(scan.status, ScanStatus.DONE)
        self.assertEqual(scan.detected_count, 4)
        self.assertIn("scan", response.data["data"])

    def test_scan_status_is_pollable(self):
        self.link()
        scan = TransactionScan.objects.get()

        response = self.client.get(f"/api/v1/banking/scans/{scan.id}")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["data"]["status"], ScanStatus.DONE)
        self.assertTrue(response.data["data"]["progress"]["is_complete"])

    def test_thin_history_is_flagged(self):
        self.link()
        connection = BankConnection.objects.get()

        with self.captureOnCommitCallbacks(execute=True):
            self.client.post(
                "/api/v1/banking/scans",
                {"connection_id": str(connection.id), "months": 3},
                format="json",
            )

        scan = TransactionScan.objects.order_by("-created_at").first()
        response = self.client.get(f"/api/v1/banking/scans/{scan.id}")

        self.assertTrue(response.data["data"]["progress"]["thin_history"])

    def test_candidates_are_listed(self):
        self.link()
        scan = TransactionScan.objects.get()

        response = self.client.get(
            f"/api/v1/banking/scans/{scan.id}/candidates"
        )

        self.assertEqual(len(response.data["data"]), 4)
        self.assertTrue(
            all(row["occurrences"] >= 3 for row in response.data["data"])
        )

    def test_category_is_guessed_where_possible(self):
        self.link()

        wework = BillDetectionCandidate.objects.get(vendor_name="WeWork")
        self.assertEqual(wework.category_guess.name, "Commercial Rent")


@override_settings(BANK_DATA_PROVIDER="mock")
class ImportTests(TestCase):

    def setUp(self):
        self.user = User.objects.create_user(
            email="import@example.com", password="Sw@yp-Test-1"
        )
        BillCategory.objects.create(
            name="Other", icon="https://e.com/i.png", color="#111"
        )
        self.client = APIClient()
        self.client.force_authenticate(user=self.user)

        with self.captureOnCommitCallbacks(execute=True):
            self.client.post(
                "/api/v1/banking/link/exchange",
                {"public_token": "public-mock-chase", "consent_accepted": True},
                format="json",
            )

        self.scan = TransactionScan.objects.get()

    def import_all(self, **headers):
        return self.client.post(
            f"/api/v1/banking/scans/{self.scan.id}/import",
            {"all": True},
            format="json",
            **headers,
        )

    def test_import_all_creates_vendors_and_bills(self):
        response = self.import_all()

        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.data["data"]["imported_count"], 4)
        self.assertEqual(Bill.objects.count(), 4)
        self.assertEqual(Vendor.objects.count(), 4)

    def test_imported_records_carry_the_right_source(self):
        self.import_all()

        self.assertTrue(
            all(v.source == VendorSource.IMPORT for v in Vendor.objects.all())
        )
        self.assertTrue(
            all(b.source == BillSource.DETECTED for b in Bill.objects.all())
        )

    def test_imported_bills_get_occurrences(self):
        self.import_all()

        for bill in Bill.objects.all():
            with self.subTest(bill=bill.vendor.name):
                self.assertGreater(bill.occurrences.count(), 0)

    def test_anchor_dates_are_in_the_future(self):
        self.import_all()

        today = timezone.localdate()
        for bill in Bill.objects.all():
            with self.subTest(bill=bill.vendor.name):
                self.assertGreater(bill.anchor_date, today)

    def test_reimport_is_a_no_op_with_a_skip_report(self):
        self.import_all()

        second = self.import_all()

        self.assertEqual(second.data["data"]["imported_count"], 0)
        self.assertEqual(second.data["data"]["skipped_count"], 4)
        self.assertEqual(Bill.objects.count(), 4)
        self.assertEqual(
            second.data["data"]["skipped"][0]["reason"], "already_imported"
        )

    def test_selective_import(self):
        candidate = BillDetectionCandidate.objects.first()

        response = self.client.post(
            f"/api/v1/banking/scans/{self.scan.id}/import",
            {"candidate_ids": [str(candidate.id)]},
            format="json",
        )

        self.assertEqual(response.data["data"]["imported_count"], 1)
        self.assertEqual(Bill.objects.count(), 1)

    def test_idempotency_key_replays_the_first_response(self):
        first = self.import_all(HTTP_IDEMPOTENCY_KEY="import-1")
        second = self.import_all(HTTP_IDEMPOTENCY_KEY="import-1")

        self.assertEqual(
            first.data["data"]["imported_count"],
            second.data["data"]["imported_count"],
        )
        self.assertEqual(Bill.objects.count(), 4)

    def test_an_existing_vendor_is_reused(self):
        category = BillCategory.objects.first()
        Vendor.objects.create(
            user=self.user, name="WeWork", category=category
        )

        self.import_all()

        self.assertEqual(
            Vendor.objects.filter(name__iexact="WeWork").count(), 1
        )

    def test_import_requires_a_selection(self):
        response = self.client.post(
            f"/api/v1/banking/scans/{self.scan.id}/import", {},
            format="json",
        )

        self.assertEqual(response.status_code, 400)

    def test_next_anchor_date_rolls_forward(self):
        service = BillImportService()

        # Day already past this month -> next month.
        self.assertEqual(
            service.next_anchor_date(
                BillFrequency.MONTHLY, 5, D(2026, 7, 20)
            ),
            D(2026, 8, 5),
        )
        # Day still ahead -> this month.
        self.assertEqual(
            service.next_anchor_date(
                BillFrequency.MONTHLY, 25, D(2026, 7, 20)
            ),
            D(2026, 7, 25),
        )
        # Day 31 in a short month clamps.
        self.assertEqual(
            service.next_anchor_date(
                BillFrequency.MONTHLY, 31, D(2026, 1, 31)
            ),
            D(2026, 2, 28),
        )


@override_settings(BANK_DATA_PROVIDER="mock")
class DisconnectTests(TestCase):

    def setUp(self):
        self.user = User.objects.create_user(
            email="disc@example.com", password="Sw@yp-Test-1"
        )
        self.category = BillCategory.objects.create(
            name="Other", icon="https://e.com/i.png", color="#111"
        )
        self.client = APIClient()
        self.client.force_authenticate(user=self.user)

        with self.captureOnCommitCallbacks(execute=True):
            self.client.post(
                "/api/v1/banking/link/exchange",
                {"public_token": "public-mock-chase", "consent_accepted": True},
                format="json",
            )

        self.connection = BankConnection.objects.get()

    def test_disconnect_marks_the_connection_and_clears_funding(self):
        response = self.client.delete(
            f"/api/v1/banking/connections/{self.connection.id}"
        )

        self.assertEqual(response.status_code, 200)
        self.connection.refresh_from_db()
        self.assertEqual(
            self.connection.status, BankConnectionStatus.DISCONNECTED
        )
        self.assertFalse(
            BankAccount.objects.filter(is_default_funding_source=True).exists()
        )

    def test_disconnect_is_blocked_while_payments_are_in_flight(self):
        provider = Provider.objects.create(
            category=self.category, provider_name="P", provider_code="P1",
            logo="https://e.com/l.png", country="US",
        )
        Payment.objects.create(
            user=self.user, provider=provider, category=self.category,
            amount=Decimal("10.00"), total=Decimal("10.00"),
            status=PaymentStatus.PROCESSING,
            transaction_reference="TX-INFLIGHT", payment_method="ACH",
        )

        response = self.client.delete(
            f"/api/v1/banking/connections/{self.connection.id}"
        )

        self.assertEqual(response.status_code, 400)
        self.connection.refresh_from_db()
        self.assertEqual(self.connection.status, BankConnectionStatus.ACTIVE)

    def test_accounts_expose_only_masks(self):
        response = self.client.get("/api/v1/banking/accounts")
        row = response.data["data"][0]

        self.assertEqual(len(row["mask"]), 4)
        self.assertIn("****", row["display"])
        self.assertNotIn("account_number", row)

    def test_default_funding_source_can_be_changed(self):
        savings = BankAccount.objects.filter(
            is_default_funding_source=False
        ).first()

        response = self.client.post(
            "/api/v1/banking/accounts",
            {"account_id": str(savings.id)},
            format="json",
        )

        self.assertEqual(response.status_code, 200)
        savings.refresh_from_db()
        self.assertTrue(savings.is_default_funding_source)
        self.assertEqual(
            BankAccount.objects.filter(is_default_funding_source=True).count(),
            1,
        )


@override_settings(BANK_DATA_PROVIDER="mock")
class OnboardingSummaryTests(TestCase):

    def setUp(self):
        self.user = User.objects.create_user(
            email="summary@example.com", password="Sw@yp-Test-1"
        )
        BillCategory.objects.create(
            name="Other", icon="https://e.com/i.png", color="#111"
        )
        self.client = APIClient()
        self.client.force_authenticate(user=self.user)

    def test_summary_before_linking_reports_no_connection(self):
        response = self.client.get("/api/v1/banking/onboarding-summary")

        self.assertEqual(response.status_code, 200)
        self.assertIsNone(response.data["data"]["connection"])

    def test_summary_after_import(self):
        with self.captureOnCommitCallbacks(execute=True):
            self.client.post(
                "/api/v1/banking/link/exchange",
                {"public_token": "public-mock-chase",
                 "consent_accepted": True},
                format="json",
            )

        scan = TransactionScan.objects.get()
        self.client.post(
            f"/api/v1/banking/scans/{scan.id}/import",
            {"all": True}, format="json",
        )

        data = self.client.get(
            "/api/v1/banking/onboarding-summary"
        ).data["data"]

        self.assertEqual(data["connection"]["institution_name"], "Chase Bank")
        self.assertIn("****", data["connection"]["funding_account"]["display"])
        self.assertEqual(data["detection"]["detected"], 4)
        self.assertEqual(data["detection"]["imported"], 4)
        self.assertEqual(data["detection"]["pending"], 0)
        self.assertEqual(data["rail_readiness"]["total_vendors"], 4)
        # Imported vendors have no payment method yet.
        self.assertEqual(data["rail_readiness"]["needs_details"], 4)

    def test_bill_totals_reconcile_with_the_bills_summary(self):
        with self.captureOnCommitCallbacks(execute=True):
            self.client.post(
                "/api/v1/banking/link/exchange",
                {"public_token": "public-mock-chase",
                 "consent_accepted": True},
                format="json",
            )

        scan = TransactionScan.objects.get()
        self.client.post(
            f"/api/v1/banking/scans/{scan.id}/import",
            {"all": True}, format="json",
        )

        onboarding = self.client.get(
            "/api/v1/banking/onboarding-summary"
        ).data["data"]["bills"]
        bills = self.client.get("/api/v1/bills/summary").data["data"]

        for key in ("overdue_count", "due_count", "upcoming_count"):
            with self.subTest(key=key):
                self.assertEqual(onboarding[key], bills[key])


@override_settings(BANK_DATA_PROVIDER="mock")
class ScanRerunTests(TestCase):
    """A re-run must report the same count, not zero (regression)."""

    def setUp(self):
        self.user = User.objects.create_user(
            email="rerun@example.com", password="Sw@yp-Test-1"
        )
        BillCategory.objects.create(
            name="Other", icon="https://e.com/i.png", color="#111"
        )
        self.client = APIClient()
        self.client.force_authenticate(user=self.user)

        with self.captureOnCommitCallbacks(execute=True):
            self.client.post(
                "/api/v1/banking/link/exchange",
                {"public_token": "public-mock-chase", "consent_accepted": True},
                format="json",
            )

    def test_rerunning_a_scan_keeps_the_detected_count(self):
        from apps.banking.services.scan_service import ScanService

        scan = TransactionScan.objects.get()
        self.assertEqual(scan.detected_count, 4)

        ScanService().run(scan)
        scan.refresh_from_db()

        self.assertEqual(scan.detected_count, 4)
        self.assertEqual(
            BillDetectionCandidate.objects.filter(scan=scan).count(), 4
        )

    def test_rerunning_does_not_duplicate_candidates(self):
        from apps.banking.services.scan_service import ScanService

        scan = TransactionScan.objects.get()
        ScanService().run(scan)
        ScanService().run(scan)

        self.assertEqual(
            BillDetectionCandidate.objects.filter(scan=scan).count(), 4
        )
