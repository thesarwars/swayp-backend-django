"""Report export, CSV and PDF (E8-S2; PRD §10-Q4 resolved — both).

`?export=` used to return 405 because the format was an open question and
guessing one would have created a contract clients then depended on. Both are
specified now, so the parameter is validated rather than refused.

Two properties matter more than the file contents:

* an export is the **whole filtered set**, not the page the user was on;
* an unrecognised format is a **400 naming what is supported**, never a silent
  fallback — a client that asked for xlsx and got a CSV would ship it to a
  user as an xlsx.
"""

import csv
import datetime as dt
import io

from django.test import TestCase
from rest_framework.test import APIClient

from apps.billing.services.subscription_service import SubscriptionService
from apps.bills.factories import BillFactory, BillOccurrenceFactory
from apps.payments.factories import PaymentFactory
from apps.reports.services.export_service import MAX_EXPORT_ROWS
from apps.vendors.factories import UserFactory

D = dt.date

URL = "/api/v1/reports"
URL_1099 = "/api/v1/reports/1099"


class ExportBase(TestCase):

    def setUp(self):
        self.user = UserFactory()
        SubscriptionService().subscribe(
            account=self.user, plan_code="STANDARD"
        )

        self.bill = BillFactory(user=self.user, anchor_date=D(2026, 9, 1))
        self.bill.vendor.name = "WeWork"
        self.bill.vendor.save()

        self.client = APIClient()
        self.client.force_authenticate(user=self.user)

    def pay(self, day, amount):
        occurrence = BillOccurrenceFactory(
            bill=self.bill, due_date=D(2026, 9, day), amount=amount
        )

        return PaymentFactory(
            user=self.user,
            bill_occurrence=occurrence,
            amount=amount,
            status="SUCCESSFUL",
        )

    def rows_of(self, response):
        text = response.content.decode()
        reader = csv.reader(io.StringIO(text))

        return [r for r in reader if r and not r[0].startswith("#")]


class CsvExportTests(ExportBase):

    def test_it_returns_a_csv_attachment(self):
        self.pay(1, "1200.00")

        response = self.client.get(f"{URL}?export=csv")

        self.assertEqual(response.status_code, 200)
        self.assertIn("text/csv", response["Content-Type"])
        self.assertIn(
            'attachment; filename="swayp-payments.csv"',
            response["Content-Disposition"],
        )

    def test_the_header_row_names_the_columns(self):
        self.pay(1, "1200.00")

        header = self.rows_of(self.client.get(f"{URL}?export=csv"))[0]

        self.assertEqual(header[0], "Date")
        self.assertIn("Vendor", header)
        self.assertIn("Total", header)
        self.assertIn("Reference", header)

    def test_every_row_is_present(self):
        for day, amount in ((1, "100.00"), (2, "200.00"), (3, "300.00")):
            self.pay(day, amount)

        rows = self.rows_of(self.client.get(f"{URL}?export=csv"))

        # header + 3 payments + totals
        self.assertEqual(len(rows), 5)

    def test_a_totals_row_closes_the_file(self):
        self.pay(1, "100.00")
        self.pay(2, "200.00")

        rows = self.rows_of(self.client.get(f"{URL}?export=csv"))

        self.assertEqual(rows[-1][0], "TOTAL")
        self.assertIn("300.00", rows[-1])

    def test_an_empty_report_still_produces_a_file(self):
        """A user with no payments gets headers, not a 404 or an error."""
        response = self.client.get(f"{URL}?export=csv")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.rows_of(response)[0][0], "Date")

    def test_a_missing_value_is_blank_not_the_word_none(self):
        """A spreadsheet column full of "None" is worse than a blank one."""
        payment = self.pay(1, "100.00")
        payment.vendor = None
        payment.save(update_fields=["vendor"])

        body = self.client.get(f"{URL}?export=csv").content.decode()

        self.assertNotIn("None", body)


class ExportIgnoresPaginationTests(ExportBase):
    """The property that matters most: you get everything, not page one."""

    def test_it_exports_past_the_page_size(self):
        for day in range(1, 26):
            self.pay(day, "10.00")

        rows = self.rows_of(
            self.client.get(f"{URL}?export=csv&pageSize=5&page=1")
        )

        # header + 25 payments + totals — not 5.
        self.assertEqual(len(rows), 27)

    def test_the_page_parameter_is_ignored(self):
        for day in range(1, 11):
            self.pay(day, "10.00")

        first = self.rows_of(self.client.get(f"{URL}?export=csv&page=1"))
        third = self.rows_of(self.client.get(f"{URL}?export=csv&page=3"))

        self.assertEqual(len(first), len(third))

    def test_the_cap_is_declared(self):
        self.assertGreaterEqual(MAX_EXPORT_ROWS, 1000)


class ExportRespectsFiltersTests(ExportBase):

    def test_a_date_filter_narrows_the_file(self):
        self.pay(1, "100.00")
        self.pay(2, "200.00")

        everything = self.rows_of(self.client.get(f"{URL}?export=csv"))
        # created_at is today for both, so an impossible window empties it.
        narrowed = self.rows_of(
            self.client.get(
                f"{URL}?export=csv&date_from=2020-01-01&date_to=2020-01-02"
            )
        )

        self.assertGreater(len(everything), len(narrowed))

    def test_another_users_vendor_filter_is_still_404(self):
        """Export must not become a way around the ownership check."""
        from apps.vendors.factories import VendorFactory

        theirs = VendorFactory()

        response = self.client.get(f"{URL}?export=csv&vendor={theirs.id}")

        self.assertEqual(response.status_code, 404)


class PdfExportTests(ExportBase):

    def test_it_returns_a_real_pdf(self):
        self.pay(1, "1200.00")

        response = self.client.get(f"{URL}?export=pdf")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "application/pdf")
        self.assertTrue(response.content.startswith(b"%PDF-"))

    def test_it_is_an_attachment_with_a_sensible_name(self):
        self.pay(1, "1200.00")

        response = self.client.get(f"{URL}?export=pdf")

        self.assertIn(
            'attachment; filename="swayp-payments.pdf"',
            response["Content-Disposition"],
        )

    def test_an_empty_report_still_renders(self):
        """reportlab raises on a one-row table, so the empty case has its own
        branch and needs its own test."""
        response = self.client.get(f"{URL}?export=pdf")

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.content.startswith(b"%PDF-"))


class Form1099ExportTests(ExportBase):

    def test_csv(self):
        self.pay(1, "1200.00")

        response = self.client.get(f"{URL_1099}?export=csv")

        self.assertEqual(response.status_code, 200)
        self.assertIn("text/csv", response["Content-Type"])
        self.assertIn("swayp-1099-", response["Content-Disposition"])

    def test_pdf(self):
        self.pay(1, "1200.00")

        response = self.client.get(f"{URL_1099}?export=pdf")

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.content.startswith(b"%PDF-"))

    def test_the_file_says_it_is_not_an_irs_form(self):
        """It is a data view. A file that looks like a filing is worse than
        one that says it isn't."""
        body = self.client.get(f"{URL_1099}?export=csv").content.decode()

        self.assertIn("Not an IRS form", body)

    def test_the_plan_gate_wins_over_the_format(self):
        """A Founding user asking for ?export=csv gets the 403 that describes
        their situation, not a file and not a format error."""
        founder = UserFactory()
        SubscriptionService().subscribe(
            account=founder, plan_code="FOUNDING"
        )

        client = APIClient()
        client.force_authenticate(user=founder)

        response = client.get(f"{URL_1099}?export=csv")

        self.assertEqual(response.status_code, 403)


class FormatValidationTests(ExportBase):

    def test_an_unknown_format_is_refused_not_defaulted(self):
        response = self.client.get(f"{URL}?export=xlsx")

        self.assertEqual(response.status_code, 400)
        self.assertIn("export", response.data["errors"])

    def test_the_error_names_the_supported_formats(self):
        message = str(
            self.client.get(f"{URL}?export=xlsx").data["errors"]["export"]
        )

        self.assertIn("csv", message)
        self.assertIn("pdf", message)

    def test_a_blank_export_is_refused(self):
        """``?export=`` with no value is still someone asking for one."""
        self.assertEqual(
            self.client.get(f"{URL}?export=").status_code, 400
        )

    def test_the_format_is_case_insensitive(self):
        self.pay(1, "100.00")

        self.assertEqual(
            self.client.get(f"{URL}?export=CSV").status_code, 200
        )

    def test_no_export_parameter_still_returns_json(self):
        self.pay(1, "100.00")

        response = self.client.get(URL)

        self.assertEqual(response.status_code, 200)
        self.assertIn("application/json", response["Content-Type"])
        self.assertIn("pagination", response.data)
