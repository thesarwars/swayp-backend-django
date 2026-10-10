"""Payment history tolerates a payment with no provider or category.

`provider` and `category` became nullable on Payment in E6-S1, but the history
serializer still read `provider.id` unconditionally. One provider-less payment
was enough to raise while rendering and turn the entire page into a 500 —
hiding every other payment along with it.
"""

import datetime as dt

from django.test import TestCase
from rest_framework.test import APIClient

from apps.bills.factories import BillFactory, BillOccurrenceFactory
from apps.common.enums import PaymentRail
from apps.payments.factories import PaymentFactory
from apps.vendors.factories import UserFactory

D = dt.date


class PaymentHistorySerializationTests(TestCase):

    def setUp(self):
        self.user = UserFactory()
        self.bill = BillFactory(user=self.user, anchor_date=D(2026, 9, 1))

        self.client = APIClient()
        self.client.force_authenticate(user=self.user)

    def a_payment(self, day=1, **kwargs):
        # Unique due date per call: one occurrence per bill per date.
        occurrence = BillOccurrenceFactory(
            bill=self.bill, due_date=D(2026, 9, day), amount="500.00"
        )

        return PaymentFactory(
            user=self.user,
            bill_occurrence=occurrence,
            rail=PaymentRail.ACH_STANDARD,
            amount="500.00",
            **kwargs,
        )

    def test_history_renders_a_payment_with_no_provider(self):
        payment = self.a_payment()
        payment.provider = None
        payment.save(update_fields=["provider"])

        response = self.client.get("/api/v1/payments/history")

        self.assertEqual(response.status_code, 200)
        self.assertIsNone(response.data["data"][0]["providerId"])
        self.assertIsNone(response.data["data"][0]["providerName"])

    def test_history_renders_a_payment_with_no_category(self):
        payment = self.a_payment()
        payment.category = None
        payment.save(update_fields=["category"])

        response = self.client.get("/api/v1/payments/history")

        self.assertEqual(response.status_code, 200)
        self.assertIsNone(response.data["data"][0]["categoryId"])

    def test_one_bad_row_does_not_hide_the_others(self):
        """The failure mode that made this worth a test of its own."""
        good = self.a_payment(day=1)
        bare = self.a_payment(day=2)
        bare.provider = None
        bare.category = None
        bare.save(update_fields=["provider", "category"])

        response = self.client.get("/api/v1/payments/history")

        self.assertEqual(response.status_code, 200)

        references = {
            row["transactionReference"] for row in response.data["data"]
        }
        self.assertIn(good.transaction_reference, references)
        self.assertIn(bare.transaction_reference, references)


class HistoryRowVendorTests(TestCase):
    """PAY-3: a history row says who was paid, and links to the bill."""

    def test_rows_carry_the_vendor_and_bill(self):
        from apps.bills.factories import BillOccurrenceFactory
        from apps.payments.factories import PaymentFactory
        from rest_framework.test import APIClient

        occurrence = BillOccurrenceFactory()
        user = occurrence.bill.user
        original = PaymentFactory(user=user, vendor=occurrence.bill.vendor)
        payment = PaymentFactory(
            user=user,
            vendor=occurrence.bill.vendor,
            bill_occurrence=occurrence,
            retry_of=original,
        )
        client = APIClient()
        client.force_authenticate(user=user)

        rows = client.get("/api/v1/payments/history").json()["data"]
        row = next(r for r in rows if r["id"] == str(payment.id))

        self.assertEqual(row["vendorId"], str(occurrence.bill.vendor_id))
        self.assertEqual(row["vendorName"], occurrence.bill.vendor.name)
        self.assertEqual(row["billId"], str(occurrence.bill_id))
        self.assertEqual(row["occurrenceId"], str(occurrence.id))
        self.assertEqual(row["replacedPaymentId"], str(original.id))
        self.assertIn("rail", row)
        self.assertIn("estimatedArrival", row)
        self.assertIn("scheduledFor", row)
