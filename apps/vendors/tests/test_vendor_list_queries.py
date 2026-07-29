"""The vendor list costs a fixed number of queries (E3-S2).

It used to cost three per vendor: one for the primary payment method and two
for the next occurrence and its bill. A customer with thirty vendors issued
ninety extra queries, so the page got slower the more successful they were —
the worst shape a performance bug can have.

The prefetch for primary methods was already in the selector. The serializer
called ``obj.payment_methods.filter(...)``, which ignores a prefetch and
re-queries, so it sat there unused.
"""

import datetime as dt
from decimal import Decimal

from django.test import TestCase
from rest_framework.test import APIClient

from apps.bills.factories import BillFactory, BillOccurrenceFactory
from apps.vendors.factories import (
    UserFactory,
    VendorFactory,
    VendorPaymentMethodFactory,
)

D = dt.date

#: One for the page count, one for the vendor page, one for the prefetched
#: primary methods, one for the acting-account lookup (E10). The next-bill
#: values ride along as subqueries on the vendor page.
EXPECTED_QUERIES = 4

URL = "/api/v1/vendors/"


class VendorListQueryCountTests(TestCase):

    def setUp(self):
        self.user = UserFactory()
        self.client = APIClient()
        self.client.force_authenticate(user=self.user)

    def seed(self, count, start=0):
        for index in range(count):
            vendor = VendorFactory(user=self.user, name=f"Vendor {start+index}")
            VendorPaymentMethodFactory(
                vendor=vendor, method_type="ACH", is_primary=True
            )
            bill = BillFactory(
                user=self.user, vendor=vendor, anchor_date=D(2026, 9, 1)
            )
            BillOccurrenceFactory(
                bill=bill, due_date=D(2026, 9, 15), amount="120.00"
            )

    def test_the_cost_does_not_grow_with_the_number_of_vendors(self):
        """The property that matters. An absolute number can drift for good
        reasons; per-row growth never can."""
        self.seed(2)
        with self.assertNumQueries(EXPECTED_QUERIES):
            self.client.get(URL)

        self.seed(18, start=2)
        with self.assertNumQueries(EXPECTED_QUERIES):
            self.client.get(URL)

    def test_the_absolute_cost_is_pinned(self):
        self.seed(5)

        with self.assertNumQueries(EXPECTED_QUERIES):
            self.client.get(URL)


class VendorListCorrectnessTests(TestCase):
    """Batching must not change a single value on the page."""

    def setUp(self):
        self.user = UserFactory()
        self.client = APIClient()
        self.client.force_authenticate(user=self.user)

    def row(self, name):
        rows = self.client.get(URL).data["items"]

        return next(r for r in rows if r["name"] == name)

    def test_a_vendor_with_an_upcoming_bill_reports_it(self):
        vendor = VendorFactory(user=self.user, name="WeWork")
        VendorPaymentMethodFactory(
            vendor=vendor, method_type="ACH", is_primary=True
        )
        bill = BillFactory(
            user=self.user, vendor=vendor, anchor_date=D(2026, 9, 1)
        )
        BillOccurrenceFactory(
            bill=bill, due_date=D(2026, 9, 15), amount="777.00"
        )

        row = self.row("WeWork")

        self.assertEqual(row["payment_rail"], "ACH")
        self.assertEqual(row["next_due"], D(2026, 9, 15))
        self.assertEqual(row["amount_period"], bill.frequency)

    def test_money_keeps_two_decimal_places(self):
        """A Subquery drops the column's scale, so $777.00 comes back as
        Decimal('777') and would serialise as "777". Every other amount in
        the API is a 2dp string, and the difference is invisible until
        something reconciles to the cent."""
        vendor = VendorFactory(user=self.user, name="Exact")
        bill = BillFactory(
            user=self.user, vendor=vendor, anchor_date=D(2026, 9, 1)
        )
        BillOccurrenceFactory(
            bill=bill, due_date=D(2026, 9, 15), amount="777.00"
        )

        self.assertEqual(
            self.row("Exact")["recurring_amount"], Decimal("777.00")
        )

    def test_a_vendor_with_nothing_reports_nulls_not_errors(self):
        VendorFactory(user=self.user, name="Bare")

        row = self.row("Bare")

        self.assertIsNone(row["payment_rail"])
        self.assertIsNone(row["recurring_amount"])
        self.assertIsNone(row["amount_period"])
        self.assertIsNone(row["next_due"])

    def test_a_settled_occurrence_is_not_the_next_bill(self):
        """open_occurrences excludes SCHEDULED and PAID, and the subquery has
        to apply the same rule the per-row lookup did."""
        from apps.common.enums import BillOccurrenceStatus

        vendor = VendorFactory(user=self.user, name="Settled")
        bill = BillFactory(
            user=self.user, vendor=vendor, anchor_date=D(2026, 9, 1)
        )
        BillOccurrenceFactory(
            bill=bill,
            due_date=D(2026, 9, 15),
            amount="100.00",
            status=BillOccurrenceStatus.PAID,
        )
        BillOccurrenceFactory(
            bill=bill, due_date=D(2026, 10, 15), amount="200.00"
        )

        row = self.row("Settled")

        self.assertEqual(row["next_due"], D(2026, 10, 15))
        self.assertEqual(row["recurring_amount"], Decimal("200.00"))

    def test_a_deleted_bill_is_not_the_next_bill(self):
        from django.utils import timezone

        vendor = VendorFactory(user=self.user, name="Deleted")
        gone = BillFactory(
            user=self.user, vendor=vendor, anchor_date=D(2026, 9, 1)
        )
        BillOccurrenceFactory(
            bill=gone, due_date=D(2026, 9, 15), amount="100.00"
        )
        gone.deleted_at = timezone.now()
        gone.save(update_fields=["deleted_at"])

        self.assertIsNone(self.row("Deleted")["next_due"])

    def test_the_nearest_occurrence_wins(self):
        vendor = VendorFactory(user=self.user, name="Ordered")
        bill = BillFactory(
            user=self.user, vendor=vendor, anchor_date=D(2026, 9, 1)
        )
        BillOccurrenceFactory(
            bill=bill, due_date=D(2026, 12, 1), amount="300.00"
        )
        BillOccurrenceFactory(
            bill=bill, due_date=D(2026, 10, 1), amount="100.00"
        )

        row = self.row("Ordered")

        self.assertEqual(row["next_due"], D(2026, 10, 1))
        self.assertEqual(row["recurring_amount"], Decimal("100.00"))

    def test_a_non_primary_method_is_not_the_rail(self):
        vendor = VendorFactory(user=self.user, name="Rails")
        VendorPaymentMethodFactory(
            vendor=vendor, method_type="CHECK", is_primary=False
        )
        VendorPaymentMethodFactory(
            vendor=vendor, method_type="ACH", is_primary=True
        )

        self.assertEqual(self.row("Rails")["payment_rail"], "ACH")
