"""Web C9: the fields the web screens needed on existing records."""

import datetime as dt

from django.test import TestCase
from rest_framework.test import APIClient

from apps.banking.factories import BankAccountFactory, BankConnectionFactory
from apps.bills.factories import BillFactory, BillOccurrenceFactory
from apps.common.enums import PaymentStatus, VendorPaymentMethodType
from apps.payments.factories import PaymentFactory
from apps.vendors.factories import UserFactory, VendorPaymentMethodFactory


class C9FieldTests(TestCase):

    def setUp(self):
        self.user = UserFactory()
        BankAccountFactory(connection=BankConnectionFactory(user=self.user),
                           is_default_funding_source=True)
        self.bill = BillFactory(user=self.user,
                                anchor_date=dt.date(2026, 1, 1))
        self.method = VendorPaymentMethodFactory(
            vendor=self.bill.vendor, method_type=VendorPaymentMethodType.ACH,
            account_last4="4821", is_primary=True,
        )
        self.client = APIClient()
        self.client.force_authenticate(user=self.user)

    def test_a_failed_payment_shows_on_its_row_with_the_id_to_resolve(self):
        occurrence = BillOccurrenceFactory(
            bill=self.bill, due_date=dt.date(2026, 1, 1), amount="10.00")
        failed = PaymentFactory(user=self.user, bill_occurrence=occurrence,
                                status=PaymentStatus.FAILED)

        row = next(r for r in self.client.get(
            "/api/v1/bills/occurrences").json()["data"]
            if r["id"] == str(occurrence.id))

        self.assertEqual(row["payment_status"], "FAILED")
        self.assertTrue(row["can_resolve"])
        self.assertEqual(row["payment_id"], str(failed.id))

    def test_payment_and_receipt_say_where_money_went(self):
        occurrence = BillOccurrenceFactory(bill=self.bill, amount="10.00")
        payment = PaymentFactory(user=self.user, bill_occurrence=occurrence,
                                 vendor=self.bill.vendor,
                                 status=PaymentStatus.SUCCESSFUL)

        data = self.client.get(f"/api/v1/payments/{payment.id}").json()["data"]

        self.assertEqual(data["payment_method_id"], str(self.method.id))
        self.assertEqual(data["payment_method_type"], "ACH")
        self.assertEqual(data["payment_account_ref"], "****4821")
        self.assertEqual(data["receipt"]["payment_method_type"], "ACH")
        self.assertEqual(data["receipt"]["account_ref"], "****4821")

    def test_bill_detail_carries_the_oldest_open_occurrence(self):
        BillOccurrenceFactory(bill=self.bill, due_date=dt.date(2026, 1, 1))

        data = self.client.get(
            f"/api/v1/bills/{self.bill.id}/details").json()["data"]

        oldest = data["oldest_open_occurrence"]
        self.assertEqual(oldest["status"], "OVERDUE")
        self.assertGreater(oldest["days_overdue"], 0)
        self.assertEqual(data["account_ref"], "****4821")

    def test_bill_list_has_ids_beside_names(self):
        row = self.client.get("/api/v1/bills").json()["data"][0]

        self.assertEqual(row["vendor_id"], str(self.bill.vendor_id))
        self.assertEqual(row["vendor_name"], self.bill.vendor.name)
        self.assertEqual(row["category_id"], str(self.bill.category_id))

    def test_bills_qr_has_the_method_and_directory_match_keys(self):
        data = self.client.post("/api/v1/bills/qr/decode", {
            "payload": f"SWAYP:vendor={self.bill.vendor.name};amount=10.00",
        }, format="json").json()["data"]

        self.assertEqual(data["payment_method"], "ACH")
        self.assertIn("directory_match", data)
