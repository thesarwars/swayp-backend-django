"""E8-S2 — GET reports/, the query-time payments report.

Three properties carry the story. The totals block describes the whole filtered
set rather than the page it happens to be sent with — asserted from the
client's side by walking every page, and cross-checked against the queryset
``GET payments/history/`` itself runs, so "totals match payment history sums" is
a comparison and not a second hardcoded constant. The row's date is the Eastern
calendar date, because TIME_ZONE is UTC and an evening payment would otherwise
be filed under tomorrow. And ``export=`` is refused before a single payment is
read, on every report route there is.
"""

import datetime as dt
from decimal import Decimal
from unittest.mock import patch

from django.db.models import Count, Sum
from django.test import TestCase, override_settings
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APIClient

from apps.bills.factories import BillOccurrenceFactory
from apps.common.dates import EASTERN, today_eastern
from apps.common.enums import Currency, PaymentStatus
from apps.payments.factories import PaymentFactory
from apps.payments.models import Payment
from apps.payments.repositories import PaymentRepository
from apps.reports.selectors.report_selector import REPORTABLE_STATUSES
from apps.vendors.factories import UserFactory, VendorFactory

REPORTS_URL = "/api/v1/reports/"

#: One aggregate for the totals, one COUNT for the paginator, one page slice,
#: plus one membership lookup to resolve the acting account (E10). Exact by
#: design: this is the N+1 guard, so a fifth query has to be a deliberate
#: edit to this number.
#:
#: The membership lookup is a single indexed read, memoised per request — a
#: constant, which is what the row-count independence test really guards.
EXPECTED_QUERIES = 4

_ZERO = Decimal("0.00")


def backdate(payment, when):
    """Move a payment's created_at.

    ``auto_now_add`` ignores assignment, so this has to go through the
    queryset. Local to the reports tests on purpose — adding a trait to the
    shared PaymentFactory would change every other app's fixtures.
    """
    Payment.objects.filter(pk=payment.pk).update(created_at=when)
    payment.refresh_from_db()

    return payment


def et_evening(day):
    """20:30 on ``day`` in New York — the instant that is already tomorrow in
    UTC, in both EST and EDT."""
    return dt.datetime(day.year, day.month, day.day, 20, 30, tzinfo=EASTERN)


class ReportTestCase(TestCase):
    """One payment per reportable status, plus the rows that break naive code.

    Amounts are distinct per status so every ``by_status`` bucket is
    identifiable by its own arithmetic, and the expected figures are folded
    from the fixture objects rather than written down, so a fixture change
    cannot leave a stale constant passing.
    """

    def setUp(self):
        self.user = UserFactory()
        self.today = today_eastern()
        self.vendor_a = VendorFactory(user=self.user, name="Alpha Utilities")
        self.vendor_b = VendorFactory(user=self.user, name="Beta Telecom")

        self.by_status = {
            payment_status: self._payment(
                amount=Decimal(100 * (index + 1)),
                payment_status=payment_status,
                vendor=self.vendor_a,
            )
            for index, payment_status in enumerate(REPORTABLE_STATUSES)
        }

        # Never reportable: the money provably never left, and the occurrence
        # was handed back to be paid by a replacement payment.
        self.cancelled = self._payment(
            amount=Decimal("999.00"),
            payment_status=PaymentStatus.CANCELLED,
            vendor=self.vendor_a,
        )

        # The only fixture with a fee, so `amount + fee == total` is a real
        # assertion rather than a tautology over zeros.
        self.vendor_b_payment = self._payment(
            amount=Decimal("1500.00"),
            fee=Decimal("5.00"),
            payment_status=PaymentStatus.SUCCESSFUL,
            vendor=self.vendor_b,
        )

        # Ad-hoc: no vendor, no occurrence. Money still moved.
        self.adhoc = self._payment(
            amount=Decimal("250.00"),
            payment_status=PaymentStatus.SUCCESSFUL,
            vendor=None,
            bill_occurrence=None,
        )

        self.occurrence = BillOccurrenceFactory(
            bill__user=self.user,
            bill__vendor=self.vendor_a,
            due_date=self.today + dt.timedelta(days=6),
            amount=Decimal("300.00"),
        )
        self.settling = self._payment(
            amount=Decimal("300.00"),
            payment_status=PaymentStatus.SCHEDULED,
            vendor=self.vendor_a,
            bill_occurrence=self.occurrence,
        )

        self.reportable = [
            *self.by_status.values(),
            self.vendor_b_payment,
            self.adhoc,
            self.settling,
        ]

        self.client = APIClient()
        self.client.force_authenticate(user=self.user)

    def _payment(
        self,
        *,
        amount,
        payment_status=PaymentStatus.PENDING,
        fee=_ZERO,
        **kwargs,
    ):
        return PaymentFactory(
            user=self.user,
            amount=amount,
            fee=fee,
            total=amount + fee,
            status=payment_status,
            **kwargs,
        )

    def _get(self, params=None):
        """The report's payload with ``pagination`` folded in beside it.

        ApiResponse puts pagination outside ``data``; every assertion below
        wants both, so the envelope is flattened once here.
        """
        response = self.client.get(REPORTS_URL, params or {})

        self.assertEqual(response.status_code, status.HTTP_200_OK)

        return {
            **response.data["data"],
            "pagination": response.data["pagination"],
        }

    def _all_rows(self, params=None):
        return self._get({**(params or {}), "pageSize": 100})["rows"]

    def _row_for(self, payment):
        rows = [
            row
            for row in self._all_rows()
            if row["payment_id"] == str(payment.id)
        ]

        self.assertEqual(len(rows), 1, f"{payment.id} appeared {len(rows)}x")

        return rows[0]

    @staticmethod
    def _folded(payments, field="total"):
        return sum((getattr(row, field) for row in payments), _ZERO)


class ReportTotalsTests(ReportTestCase):

    def test_totals_match_the_payment_history_sum(self):
        # PaymentRepository.list_by_user is not a re-derivation: it is literally
        # what GET payments/history/ runs (view -> PaymentService
        # .payment_history -> PaymentSelector.list_payments -> here). The
        # comparison stops at the repository rather than going over HTTP
        # because PaymentSerializer.providerId reads source="provider.id" with
        # no null handling (apps/payments/serializers.py:11-25), so that
        # endpoint 500s on any vendor-only payment — an E6 defect this story
        # must not reach into.
        expected = (
            PaymentRepository.list_by_user(user=self.user)
            .filter(status__in=REPORTABLE_STATUSES)
            .aggregate(
                amount=Sum("amount"),
                fee=Sum("fee"),
                total=Sum("total"),
                count=Count("id"),
            )
        )

        # pageSize=1 so a page-scoped total cannot accidentally pass. No date
        # filter on either side: payment history buckets created_at in UTC
        # (apps/payments/repositories.py:55-63) while the report buckets it in
        # Eastern, so the only delta under test is the status restriction — and
        # the fixture carries a CANCELLED payment, so dropping that filter
        # fails this test rather than passing it.
        totals = self._get({"pageSize": 1})["totals"]

        self.assertEqual(Decimal(totals["amount"]), expected["amount"])
        self.assertEqual(Decimal(totals["fee"]), expected["fee"])
        self.assertEqual(Decimal(totals["total"]), expected["total"])
        self.assertEqual(totals["count"], expected["count"])
        self.assertEqual(
            Decimal(totals["amount"]) + Decimal(totals["fee"]),
            Decimal(totals["total"]),
        )
        self.assertEqual(
            PaymentRepository.list_by_user(user=self.user).count(),
            totals["count"] + 1,
        )

    def test_totals_equal_the_sum_of_every_page(self):
        walked_total = _ZERO
        walked_rows = 0
        page = 1
        headline = None

        while True:
            body = self._get({"pageSize": 2, "page": page})

            if headline is None:
                headline = body["totals"]

            walked_total += sum(
                (Decimal(row["total"]) for row in body["rows"]), _ZERO
            )
            walked_rows += len(body["rows"])

            if not body["pagination"]["hasNext"]:
                break

            page += 1

        self.assertGreater(page, 1, "fixture must span more than one page")
        self.assertEqual(walked_rows, headline["count"])
        self.assertEqual(walked_total, Decimal(headline["total"]))
        self.assertEqual(walked_total, self._folded(self.reportable))

    def test_totals_are_identical_on_every_page(self):
        first = self._get({"pageSize": 1, "page": 1})["totals"]
        third = self._get({"pageSize": 1, "page": 3})["totals"]

        self.assertEqual(first, third)
        self.assertEqual(first["count"], len(self.reportable))

    def test_failed_returned_and_refunded_appear_in_their_own_buckets(self):
        body = self._get({"pageSize": 100})
        by_status = body["totals"]["by_status"]
        references = {row["reference"] for row in body["rows"]}

        for reversal in (
            PaymentStatus.FAILED,
            PaymentStatus.RETURNED,
            PaymentStatus.REFUNDED,
        ):
            payment = self.by_status[reversal]

            self.assertIn(payment.transaction_reference, references)
            self.assertEqual(
                Decimal(by_status[reversal]["total"]), payment.total
            )
            self.assertEqual(by_status[reversal]["count"], 1)

        # One figure never swallows another: the buckets add up to the flat
        # headline, which is the only reason both can be published.
        self.assertEqual(
            sum(
                (Decimal(bucket["total"]) for bucket in by_status.values()),
                _ZERO,
            ),
            Decimal(body["totals"]["total"]),
        )

    def test_cancelled_payments_are_absent_from_rows_and_totals(self):
        body = self._get({"pageSize": 100})
        totals = body["totals"]

        self.assertNotIn(
            self.cancelled.transaction_reference,
            {row["reference"] for row in body["rows"]},
        )
        self.assertNotIn(PaymentStatus.CANCELLED, totals["by_status"])
        self.assertEqual(totals["count"], len(self.reportable))
        self.assertEqual(
            Decimal(totals["total"]), self._folded(self.reportable)
        )

    def test_mixed_currencies_leave_the_flat_currency_null(self):
        euro = self._payment(
            amount=Decimal("40.00"),
            payment_status=PaymentStatus.SUCCESSFUL,
            vendor=self.vendor_b,
            currency=Currency.EUR,
        )

        totals = self._get({"pageSize": 100})["totals"]
        by_currency = {
            bucket["currency"]: bucket for bucket in totals["by_currency"]
        }

        # The flat figures would be adding EUR to USD, so the currency label is
        # withheld and by_currency is the only honest breakdown.
        self.assertIsNone(totals["currency"])
        self.assertEqual(sorted(by_currency), [Currency.EUR, Currency.USD])
        self.assertEqual(Decimal(by_currency[Currency.EUR]["total"]), euro.total)
        self.assertEqual(
            Decimal(by_currency[Currency.USD]["total"]),
            self._folded(self.reportable),
        )

    def test_single_currency_is_named_on_the_flat_block(self):
        totals = self._get({"pageSize": 100})["totals"]

        self.assertEqual(totals["currency"], Currency.USD)


class ReportFilterTests(ReportTestCase):

    def test_both_filters_are_optional(self):
        body = self._get()

        self.assertEqual(
            body["filters"],
            {"vendor": None, "date_from": None, "date_to": None},
        )
        self.assertEqual(body["totals"]["count"], len(self.reportable))
        self.assertEqual(
            body["pagination"]["totalItems"], len(self.reportable)
        )

    def test_report_is_paginated_with_the_shared_envelope(self):
        body = self._get({"pageSize": 2})

        self.assertEqual(len(body["rows"]), 2)
        self.assertEqual(
            body["pagination"],
            {
                "page": 1,
                "pageSize": 2,
                "totalPages": 5,
                "totalItems": len(self.reportable),
                "hasNext": True,
                "hasPrevious": False,
            },
        )

    def test_vendor_filter_narrows_rows_and_totals_together(self):
        expected = [*self.by_status.values(), self.settling]

        body = self._get({"vendor": str(self.vendor_a.id), "pageSize": 100})

        self.assertEqual(
            {row["payment_id"] for row in body["rows"]},
            {str(payment.id) for payment in expected},
        )
        self.assertEqual(body["filters"]["vendor"], str(self.vendor_a.id))
        self.assertEqual(body["totals"]["count"], len(expected))
        self.assertEqual(
            Decimal(body["totals"]["total"]), self._folded(expected)
        )

    def test_date_range_filter_narrows_rows_and_totals_together(self):
        days = [self.today - dt.timedelta(days=offset) for offset in (30, 29, 28)]
        dated = [
            backdate(
                self._payment(
                    amount=Decimal("11.00") * (index + 1),
                    payment_status=PaymentStatus.SUCCESSFUL,
                    vendor=self.vendor_b,
                ),
                et_evening(day) - dt.timedelta(hours=12),
            )
            for index, day in enumerate(days)
        ]
        middle_day, middle_payment = days[1], dated[1]

        body = self._get(
            {
                "date_from": middle_day.isoformat(),
                "date_to": middle_day.isoformat(),
                "pageSize": 100,
            }
        )

        self.assertEqual(len(body["rows"]), 1)
        self.assertEqual(
            body["rows"][0]["payment_id"], str(middle_payment.id)
        )
        self.assertEqual(
            Decimal(body["totals"]["total"]), middle_payment.total
        )
        self.assertEqual(
            body["filters"]["date_from"], middle_day.isoformat()
        )

    def test_empty_result_is_a_200_with_zero_totals_and_no_rows(self):
        self.client.force_authenticate(user=UserFactory())

        response = self.client.get(REPORTS_URL)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["message"], "Report generated.")
        self.assertEqual(response.data["data"]["rows"], [])
        self.assertEqual(
            response.data["data"]["totals"],
            {
                "count": 0,
                "currency": None,
                "amount": "0.00",
                "fee": "0.00",
                "total": "0.00",
                "by_status": {},
                "by_currency": [],
            },
        )
        self.assertEqual(response.data["pagination"]["totalItems"], 0)
        self.assertEqual(response.data["pagination"]["totalPages"], 1)

    def test_inverted_date_range_is_unprocessable(self):
        response = self.client.get(
            REPORTS_URL,
            {
                "date_from": (self.today + dt.timedelta(days=30)).isoformat(),
                "date_to": self.today.isoformat(),
            },
        )

        self.assertEqual(
            response.status_code, status.HTTP_422_UNPROCESSABLE_ENTITY
        )
        self.assertFalse(response.data["success"])
        self.assertIn("date_from", response.data["message"])
        self.assertIn("date_to", response.data["message"])

    def test_another_users_payments_never_appear(self):
        stranger = UserFactory()
        stranger_vendor = VendorFactory(user=stranger, name="Gamma Water")
        PaymentFactory(
            user=stranger,
            vendor=stranger_vendor,
            amount=Decimal("77.00"),
            total=Decimal("77.00"),
            status=PaymentStatus.SUCCESSFUL,
            transaction_reference="SWP-20260801-9999",
        )

        body = self._get({"pageSize": 100})

        self.assertNotIn(
            "SWP-20260801-9999",
            {row["reference"] for row in body["rows"]},
        )
        self.assertEqual(body["totals"]["count"], len(self.reportable))

        # A foreign vendor id is "not found", not an empty 200: the report has
        # no reason to tell a caller which vendor ids exist.
        response = self.client.get(
            REPORTS_URL, {"vendor": str(stranger_vendor.id)}
        )

        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
        self.assertEqual(response.data["message"], "Vendor not found.")


class ReportRowTests(ReportTestCase):

    def test_row_date_is_the_eastern_calendar_date_not_the_utc_one(self):
        day = self.today - dt.timedelta(days=40)
        payment = backdate(
            self._payment(
                amount=Decimal("42.00"),
                payment_status=PaymentStatus.SUCCESSFUL,
                vendor=self.vendor_a,
            ),
            et_evening(day),
        )

        # The trap: stored UTC has already rolled over to the next day.
        self.assertEqual(
            payment.created_at.astimezone(dt.UTC).date(),
            day + dt.timedelta(days=1),
        )

        self.assertEqual(self._row_for(payment)["date"], day.isoformat())

        included = self._all_rows({"date_to": day.isoformat()})
        excluded = self._all_rows(
            {"date_from": (day + dt.timedelta(days=1)).isoformat()}
        )

        self.assertEqual(
            [row["payment_id"] for row in included], [str(payment.id)]
        )
        self.assertNotIn(
            str(payment.id), [row["payment_id"] for row in excluded]
        )

    def test_row_shows_null_vendor_and_null_bill_for_an_ad_hoc_payment(self):
        row = self._row_for(self.adhoc)

        self.assertIsNone(row["vendor"])
        self.assertIsNone(row["bill"])
        self.assertEqual(row["reference"], self.adhoc.transaction_reference)
        self.assertEqual(Decimal(row["amount"]), self.adhoc.amount)

        # Money that moved is still counted, and the vendor slot is never
        # backfilled with a directory provider's catalogue name.
        totals = self._get({"pageSize": 100})["totals"]

        self.assertEqual(
            Decimal(totals["total"]), self._folded(self.reportable)
        )

    def test_row_carries_the_bill_block_when_the_payment_settles_an_occurrence(
        self,
    ):
        row = self._row_for(self.settling)

        self.assertEqual(
            row["bill"],
            {
                "id": str(self.occurrence.bill_id),
                "occurrence_id": str(self.occurrence.id),
                "due_date": self.occurrence.due_date.isoformat(),
            },
        )
        self.assertEqual(row["vendor"]["name"], self.vendor_a.name)
        self.assertEqual(row["status"], PaymentStatus.SCHEDULED)
        self.assertEqual(row["rail"], self.settling.rail)

    def test_row_survives_its_occurrence_being_deleted(self):
        self.occurrence.delete()

        row = self._row_for(self.settling)

        self.assertIsNone(row["bill"])
        self.assertEqual(row["vendor"]["id"], str(self.vendor_a.id))
        self.assertEqual(
            Decimal(self._get({"pageSize": 100})["totals"]["total"]),
            self._folded(self.reportable),
        )

    def test_requires_authentication(self):
        response = APIClient().get(REPORTS_URL)

        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)


class ReportExportTests(ReportTestCase):
    """Export is supported now (PRD §10-Q4 resolved: CSV and PDF).

    These used to assert a 405. The format was an open question and guessing
    one would have created a contract clients then depended on; both are
    specified now, so the parameter is validated instead of refused.

    File contents are covered in test_export.py. What is kept here is the
    property the old class really guarded — that **every** report route
    behaves the same way, so a new endpoint cannot quietly diverge.
    """

    def test_both_formats_are_served(self):
        for requested, content_type in (
            ("csv", "text/csv"),
            ("pdf", "application/pdf"),
        ):
            with self.subTest(export=requested):
                response = self.client.get(
                    REPORTS_URL, {"export": requested}
                )

                self.assertEqual(response.status_code, status.HTTP_200_OK)
                self.assertIn(content_type, response["Content-Type"])
                self.assertIn(
                    "attachment", response["Content-Disposition"]
                )

    def test_an_unknown_format_is_refused_rather_than_defaulted(self):
        """A client that asked for xlsx and received a CSV would ship it to a
        user as an xlsx."""
        response = self.client.get(REPORTS_URL, {"export": "xlsx"})

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertFalse(response.data["success"])
        self.assertNotIn("text/csv", response["Content-Type"])

    def test_a_blank_export_is_refused(self):
        """``?export=`` with no value is still someone asking for one, and it
        is the first spelling a client trying it out would send."""
        response = self.client.get(REPORTS_URL, {"export": ""})

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_the_format_is_validated_before_any_payment_is_read(self):
        target = (
            "apps.reports.services.report_service."
            "ReportService.payments_report"
        )

        with patch(target) as report:
            response = self.client.get(
                REPORTS_URL,
                {"export": "xlsx", "vendor": str(self.vendor_a.id)},
            )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertFalse(report.called)

    @override_settings(DEFAULT_PLAN_CODE="ENTERPRISE")
    def test_every_report_endpoint_supports_export(self):
        from apps.reports.api.urls import urlpatterns

        self.assertTrue(urlpatterns)

        for pattern in urlpatterns:
            with self.subTest(route=pattern.name):
                # ENTERPRISE so the 1099 plan gate cannot shadow the result:
                # a route that stops inheriting _ExportSerializer has to fail
                # here rather than silently lose the capability.
                response = self.client.get(
                    reverse(pattern.name), {"export": "csv"}
                )

                self.assertEqual(response.status_code, status.HTTP_200_OK)
                self.assertIn("text/csv", response["Content-Type"])


class ReportQueryCountTests(TestCase):
    """The endpoint's cost must not follow its row count."""

    def setUp(self):
        self.user = UserFactory()
        self.today = today_eastern()
        self.client = APIClient()
        self.client.force_authenticate(user=self.user)

    def _seed(self, payments, vendors):
        vendor_rows = [
            VendorFactory(user=self.user, name=f"Vendor {index}")
            for index in range(vendors)
        ]

        for index in range(payments):
            vendor = vendor_rows[index % vendors]
            occurrence = BillOccurrenceFactory(
                bill__user=self.user,
                bill__vendor=vendor,
                due_date=self.today + dt.timedelta(days=index),
                amount=Decimal("175.25"),
            )
            PaymentFactory(
                user=self.user,
                vendor=vendor,
                bill_occurrence=occurrence,
                amount=Decimal("175.25"),
                total=Decimal("175.25"),
                status=PaymentStatus.SUCCESSFUL,
            )

    def test_report_query_count_is_constant_regardless_of_row_count(self):
        self._seed(payments=5, vendors=2)

        with self.assertNumQueries(EXPECTED_QUERIES):
            self.client.get(REPORTS_URL, {"pageSize": 100})

        self._seed(payments=45, vendors=10)

        self.assertEqual(Payment.objects.filter(user=self.user).count(), 50)

        with self.assertNumQueries(EXPECTED_QUERIES):
            self.client.get(REPORTS_URL, {"pageSize": 100})
