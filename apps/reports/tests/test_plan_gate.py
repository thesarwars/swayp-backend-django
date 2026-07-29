"""E8-S2 — the plan entitlement seam and the 1099 report it gates.

No Plan or Subscription table exists yet (E9 owns them), so the entitlement
question is answered by ``apps/common/plans.py`` behind one replaceable
function. What is asserted here is that the seam FAILS CLOSED: the default
grants nothing, a typo in the setting grants nothing, a gate written against a
code that does not exist stays shut, and a Founding user asking for the 1099
report gets a 403 that says why rather than an empty 200 they could file taxes
on.
"""

import datetime as dt
from decimal import Decimal

from django.conf import settings
from django.test import TestCase, override_settings
from rest_framework import status
from rest_framework.test import APIClient

from apps.common.dates import today_eastern
from apps.common.enums import PaymentStatus, PlanCode
from apps.common.plans import PLAN_ORDER, current_plan_code, has_plan_at_least
from apps.payments.factories import PaymentFactory
from apps.reports.tests.test_reports import backdate, et_evening
from apps.vendors.factories import UserFactory, VendorFactory

REPORT_1099_URL = "/api/v1/reports/1099/"

_ZERO = Decimal("0.00")


class PlanSeamTests(TestCase):

    def setUp(self):
        self.user = UserFactory()

    def test_default_plan_is_founding(self):
        # No override: config/settings/test.py inherits base, so this is the
        # value a production deploy gets. Asserted on the setting as well as on
        # the function, so an environment that quietly set DEFAULT_PLAN_CODE
        # fails here rather than opening the gate somewhere downstream.
        self.assertEqual(settings.DEFAULT_PLAN_CODE, PlanCode.FOUNDING)
        self.assertEqual(current_plan_code(self.user), PlanCode.FOUNDING)
        self.assertFalse(has_plan_at_least(self.user, PlanCode.STANDARD))
        self.assertTrue(has_plan_at_least(self.user, PlanCode.FOUNDING))

    def test_unknown_plan_code_degrades_to_founding(self):
        for typo in ("STANDRD", "", "ENTERPRISE_PLUS", "standard"):
            with self.subTest(code=typo), override_settings(
                DEFAULT_PLAN_CODE=typo
            ):
                # A misconfiguration must deny, never grant, and never 500 the
                # whole reports surface.
                self.assertEqual(
                    current_plan_code(self.user), PlanCode.FOUNDING
                )
                self.assertFalse(
                    has_plan_at_least(self.user, PlanCode.STANDARD)
                )

    @override_settings(DEFAULT_PLAN_CODE="ENTERPRISE")
    def test_unknown_minimum_never_satisfied(self):
        self.assertEqual(current_plan_code(self.user), PlanCode.ENTERPRISE)
        self.assertFalse(has_plan_at_least(self.user, "PLATINUM"))

    def test_plan_order_is_ascending_and_founding_is_lowest(self):
        self.assertEqual(
            PLAN_ORDER,
            (PlanCode.FOUNDING, PlanCode.STANDARD, PlanCode.ENTERPRISE),
        )

        expected = {
            PlanCode.FOUNDING: {PlanCode.FOUNDING},
            PlanCode.STANDARD: {PlanCode.FOUNDING, PlanCode.STANDARD},
            PlanCode.ENTERPRISE: set(PLAN_ORDER),
        }

        for code, satisfied in expected.items():
            with self.subTest(plan=code), override_settings(
                DEFAULT_PLAN_CODE=code
            ):
                for minimum in PLAN_ORDER:
                    self.assertEqual(
                        has_plan_at_least(self.user, minimum),
                        minimum in satisfied,
                        f"{code} vs minimum {minimum}",
                    )


class Form1099TestCase(TestCase):
    """One vendor paid twice, one paid once, one payment with no vendor."""

    def setUp(self):
        self.user = UserFactory()
        self.year = today_eastern().year
        self.vendor_a = VendorFactory(user=self.user, name="Alpha Utilities")
        self.vendor_b = VendorFactory(user=self.user, name="Beta Telecom")

        self.paid_a = [
            self._payment(
                amount=Decimal("1000.00"), fee=Decimal("10.00"),
                vendor=self.vendor_a,
            ),
            self._payment(amount=Decimal("500.00"), vendor=self.vendor_a),
        ]
        self.paid_b = [
            self._payment(amount=Decimal("250.00"), vendor=self.vendor_b)
        ]
        self.vendorless = self._payment(
            amount=Decimal("125.00"), vendor=None
        )

        # Not compensation: a 1099 reports money that actually reached a payee.
        self.not_paid = [
            self._payment(
                amount=Decimal("700.00"),
                payment_status=PaymentStatus.FAILED,
                vendor=self.vendor_a,
            ),
            self._payment(
                amount=Decimal("300.00"),
                payment_status=PaymentStatus.PENDING,
                vendor=self.vendor_a,
            ),
        ]

        self.client = APIClient()
        self.client.force_authenticate(user=self.user)

    def _payment(
        self,
        *,
        amount,
        payment_status=PaymentStatus.SUCCESSFUL,
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

    def _report(self, params=None):
        response = self.client.get(REPORT_1099_URL, params or {})

        self.assertEqual(response.status_code, status.HTTP_200_OK)

        return response.data["data"]

    @staticmethod
    def _folded(payments):
        return sum((payment.total for payment in payments), _ZERO)


class Form1099PlanGateTests(Form1099TestCase):

    def test_1099_is_forbidden_on_founding(self):
        response = self.client.get(REPORT_1099_URL)

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertFalse(response.data["success"])
        self.assertIn("Standard plan", response.data["message"])
        # 403, not an empty 200: an empty 1099 dataset is indistinguishable
        # from "you paid no vendors this year", and a user who files on that
        # basis has been actively misled.
        self.assertNotIn("data", response.data)

    def test_1099_is_forbidden_even_with_export(self):
        response = self.client.get(REPORT_1099_URL, {"export": "csv"})

        # The plan gate runs before query parsing on this view, so a user who
        # cannot reach the report at all is told the reason that applies to
        # them rather than one about a format nobody has.
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertIn("Standard plan", response.data["message"])

    def test_1099_is_served_on_standard_and_enterprise(self):
        expected_rows = {
            str(self.vendor_a.id): self._folded(self.paid_a),
            str(self.vendor_b.id): self._folded(self.paid_b),
        }

        for plan in (PlanCode.STANDARD, PlanCode.ENTERPRISE):
            with self.subTest(plan=plan), override_settings(
                DEFAULT_PLAN_CODE=plan
            ):
                data = self._report({"year": self.year})
                rows = {row["vendor_id"]: row for row in data["rows"]}

                self.assertEqual(data["year"], self.year)
                self.assertEqual(set(rows), set(expected_rows))
                # Biggest payee first: that is the order a 1099 is read in.
                self.assertEqual(
                    data["rows"][0]["vendor_id"], str(self.vendor_a.id)
                )

                for vendor_id, total in expected_rows.items():
                    self.assertEqual(Decimal(rows[vendor_id]["total"]), total)

                self.assertEqual(
                    rows[str(self.vendor_a.id)]["vendor_name"],
                    self.vendor_a.name,
                )
                self.assertEqual(rows[str(self.vendor_a.id)]["count"], 2)

                # Rows plus unattributed reconcile exactly to totals.
                self.assertEqual(
                    sum(
                        (Decimal(row["total"]) for row in data["rows"]),
                        Decimal(data["unattributed"]["total"]),
                    ),
                    Decimal(data["totals"]["total"]),
                )

    @override_settings(DEFAULT_PLAN_CODE="STANDARD")
    def test_1099_counts_only_successful_payments(self):
        data = self._report({"year": self.year})
        row = next(
            row
            for row in data["rows"]
            if row["vendor_id"] == str(self.vendor_a.id)
        )

        self.assertEqual(Decimal(row["total"]), self._folded(self.paid_a))
        self.assertEqual(row["count"], len(self.paid_a))
        self.assertEqual(
            Decimal(data["totals"]["total"]),
            self._folded(
                [*self.paid_a, *self.paid_b, self.vendorless]
            ),
        )

    @override_settings(DEFAULT_PLAN_CODE="STANDARD")
    def test_1099_reports_vendorless_payments_as_unattributed(self):
        data = self._report({"year": self.year})

        self.assertNotIn(
            None, [row["vendor_id"] for row in data["rows"]]
        )
        self.assertEqual(
            Decimal(data["unattributed"]["total"]), self.vendorless.total
        )
        self.assertEqual(data["unattributed"]["count"], 1)
        self.assertEqual(
            Decimal(data["totals"]["total"])
            - Decimal(data["unattributed"]["total"]),
            self._folded([*self.paid_a, *self.paid_b]),
        )

    @override_settings(DEFAULT_PLAN_CODE="STANDARD")
    def test_1099_defaults_to_the_current_eastern_tax_year(self):
        data = self._report()

        self.assertEqual(data["year"], self.year)
        self.assertEqual(
            Decimal(data["totals"]["total"]),
            self._folded([*self.paid_a, *self.paid_b, self.vendorless]),
        )

    @override_settings(DEFAULT_PLAN_CODE="STANDARD")
    def test_1099_year_bounds_are_eastern_not_utc(self):
        # 20:30 ET on 31 December is already 1 January in UTC, so a UTC year
        # boundary would file this payment under the wrong tax year.
        last_new_years_eve = dt.date(self.year - 1, 12, 31)
        stale = backdate(
            self._payment(amount=Decimal("4444.00"), vendor=self.vendor_a),
            et_evening(last_new_years_eve),
        )

        self.assertEqual(
            stale.created_at.astimezone(dt.UTC).date(),
            dt.date(self.year, 1, 1),
        )

        current = self._report({"year": self.year})
        previous = self._report({"year": self.year - 1})

        self.assertEqual(
            Decimal(current["totals"]["total"]),
            self._folded([*self.paid_a, *self.paid_b, self.vendorless]),
        )
        self.assertEqual(
            Decimal(previous["totals"]["total"]), stale.total
        )

    @override_settings(DEFAULT_PLAN_CODE="STANDARD")
    def test_1099_year_in_the_future_is_unprocessable(self):
        # today_eastern() rather than timezone.localdate() so the test does not
        # flip on New Year's Eve evening.
        response = self.client.get(
            REPORT_1099_URL, {"year": today_eastern().year + 1}
        )

        self.assertEqual(
            response.status_code, status.HTTP_422_UNPROCESSABLE_ENTITY
        )
        self.assertFalse(response.data["success"])

    @override_settings(DEFAULT_PLAN_CODE="STANDARD")
    def test_1099_rejects_a_filter_it_cannot_honour(self):
        # DRF silently discards undeclared query params, so a caller who copies
        # ?vendor=/?date_from= across from the payments report would otherwise
        # get a full-year answer that looks filtered.
        for ignored in ("vendor", "date_from", "date_to"):
            with self.subTest(param=ignored):
                response = self.client.get(
                    REPORT_1099_URL, {ignored: "2026-01-01"}
                )

                self.assertEqual(
                    response.status_code, status.HTTP_400_BAD_REQUEST
                )
                self.assertIn(ignored, response.data["message"])

    @override_settings(DEFAULT_PLAN_CODE="STANDARD")
    def test_1099_requires_authentication(self):
        response = APIClient().get(REPORT_1099_URL)

        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)
