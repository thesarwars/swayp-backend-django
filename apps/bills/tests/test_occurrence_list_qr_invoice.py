"""Occurrence list, payment history, QR and invoice (E4-S2 / S4 / S7)."""

import datetime as dt
from decimal import Decimal

from django.test import TestCase
from rest_framework.test import APIClient

from apps.bill_categories.models import BillCategory
from apps.bills.models.bill import Bill
from apps.bills.models.bill_occurrence import BillOccurrence
from apps.bills.services.invoice_service import InvoiceService
from apps.bills.services.qr_service import BillQRService
from apps.common.enums import BillFrequency, BillOccurrenceStatus, PaymentStatus
from apps.payments.models import Payment
from apps.providers.models import Provider
from apps.users.models import User
from apps.vendors.models import Vendor, VendorPaymentMethod

D = dt.date


class BillFixtureMixin:

    def setUp(self):
        self.user = User.objects.create_user(
            email="rows@example.com", password="Sw@yp-Test-1"
        )
        self.category = BillCategory.objects.create(
            name="Commercial Rent", icon="https://e.com/i.png", color="#111"
        )
        self.vendor = Vendor.objects.create(
            user=self.user, name="WeWork", category=self.category,
            logo="https://cdn.swayp.com/logos/wework.png",
        )
        self.other_vendor = Vendor.objects.create(
            user=self.user, name="Verizon", category=self.category
        )
        self.bill = Bill.objects.create(
            user=self.user, vendor=self.vendor, category=self.category,
            amount=Decimal("3200.00"), frequency=BillFrequency.MONTHLY,
            anchor_date=D(2026, 1, 15),
        )
        self.other_bill = Bill.objects.create(
            user=self.user, vendor=self.other_vendor, category=self.category,
            amount=Decimal("389.00"), frequency=BillFrequency.MONTHLY,
            anchor_date=D(2026, 1, 20),
        )
        self.client = APIClient()
        self.client.force_authenticate(user=self.user)

    def occurrence(self, bill, due_date, status=BillOccurrenceStatus.UPCOMING,
                   amount="3200.00"):
        return BillOccurrence.objects.create(
            bill=bill, due_date=due_date, amount=amount, status=status
        )


class OccurrenceListTests(BillFixtureMixin, TestCase):

    def test_rows_carry_vendor_and_computed_status(self):
        self.occurrence(self.bill, D(2030, 1, 1))

        response = self.client.get("/api/v1/bills/occurrences")
        row = response.data["data"][0]

        self.assertEqual(response.status_code, 200)
        self.assertEqual(row["vendor_name"], "WeWork")
        self.assertEqual(
            row["vendor_logo"], "https://cdn.swayp.com/logos/wework.png"
        )
        self.assertEqual(row["status"], BillOccurrenceStatus.UPCOMING)

    def test_response_is_paginated(self):
        for day in range(1, 6):
            self.occurrence(self.bill, D(2030, 1, day))

        response = self.client.get("/api/v1/bills/occurrences?pageSize=2")

        self.assertEqual(len(response.data["data"]), 2)
        self.assertEqual(response.data["pagination"]["totalItems"], 5)

    def test_status_filter_uses_the_computed_value(self):
        self.occurrence(self.bill, D(2020, 1, 1))   # overdue
        self.occurrence(self.bill, D(2030, 1, 1))   # upcoming

        overdue = self.client.get(
            "/api/v1/bills/occurrences?status=OVERDUE"
        )

        self.assertEqual(len(overdue.data["data"]), 1)
        self.assertEqual(overdue.data["data"][0]["status"], "OVERDUE")

    def test_vendor_filter(self):
        self.occurrence(self.bill, D(2030, 1, 1))
        self.occurrence(self.other_bill, D(2030, 1, 2), amount="389.00")

        response = self.client.get(
            f"/api/v1/bills/occurrences?vendor={self.other_vendor.id}"
        )

        self.assertEqual(len(response.data["data"]), 1)
        self.assertEqual(response.data["data"][0]["vendor_name"], "Verizon")

    def test_date_range_filter(self):
        self.occurrence(self.bill, D(2030, 1, 1))
        self.occurrence(self.bill, D(2030, 6, 1))
        self.occurrence(self.bill, D(2030, 12, 1))

        response = self.client.get(
            "/api/v1/bills/occurrences"
            "?date_from=2030-05-01&date_to=2030-07-01"
        )

        self.assertEqual(len(response.data["data"]), 1)
        self.assertEqual(response.data["data"][0]["due_date"], "2030-06-01")

    def test_deleted_bills_drop_out(self):
        self.occurrence(self.bill, D(2030, 1, 1))
        from django.utils import timezone

        self.bill.deleted_at = timezone.now()
        self.bill.save(update_fields=["deleted_at"])

        response = self.client.get("/api/v1/bills/occurrences")

        self.assertEqual(response.data["data"], [])

    def test_another_users_occurrences_are_invisible(self):
        self.occurrence(self.bill, D(2030, 1, 1))

        other = User.objects.create_user(
            email="nosy@example.com", password="Sw@yp-Test-2"
        )
        client = APIClient()
        client.force_authenticate(user=other)

        self.assertEqual(
            client.get("/api/v1/bills/occurrences").data["data"], []
        )


class PaymentHistoryTests(BillFixtureMixin, TestCase):

    def make_payment(self, occurrence, status=PaymentStatus.SUCCESSFUL,
                     reference="TX-1"):
        provider = Provider.objects.create(
            category=self.category, provider_name="Mock",
            provider_code=f"MOCK-{reference}", logo="https://e.com/l.png",
            country="US",
        )
        return Payment.objects.create(
            user=self.user, provider=provider, category=self.category,
            bill_occurrence=occurrence, amount=Decimal("3200.00"),
            total=Decimal("3200.00"), status=status,
            transaction_reference=reference, payment_method="ACH",
        )

    def test_history_joins_through_the_occurrence(self):
        occurrence = self.occurrence(self.bill, D(2026, 2, 15))
        self.make_payment(occurrence)

        response = self.client.get(
            f"/api/v1/bills/{self.bill.id}/payments"
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.data["data"]), 1)
        self.assertEqual(response.data["data"][0]["due_date"], "2026-02-15")

    def test_a_retry_is_its_own_row_on_the_same_occurrence(self):
        occurrence = self.occurrence(self.bill, D(2026, 2, 15))
        self.make_payment(occurrence, PaymentStatus.FAILED, "TX-FAIL")
        self.make_payment(occurrence, PaymentStatus.SUCCESSFUL, "TX-OK")

        response = self.client.get(
            f"/api/v1/bills/{self.bill.id}/payments"
        )

        self.assertEqual(len(response.data["data"]), 2)
        self.assertEqual(
            {row["occurrence_id"] for row in response.data["data"]},
            {str(occurrence.id)},
        )

    def test_another_bills_payments_are_excluded(self):
        self.make_payment(self.occurrence(self.bill, D(2026, 2, 15)))
        self.make_payment(
            self.occurrence(self.other_bill, D(2026, 2, 20), amount="389.00"),
            reference="TX-OTHER",
        )

        response = self.client.get(
            f"/api/v1/bills/{self.bill.id}/payments"
        )

        self.assertEqual(len(response.data["data"]), 1)

    def test_empty_history_is_an_empty_list(self):
        response = self.client.get(
            f"/api/v1/bills/{self.bill.id}/payments"
        )

        self.assertEqual(response.data["data"], [])


class BillQRTests(TestCase):

    def setUp(self):
        self.service = BillQRService()

    def test_structured_payload_yields_prefill_fields(self):
        result = self.service.decode(
            payload="SWAYP:vendor=WeWork;amount=3200.00;due=2026-09-01;ref=WW-88"
        )

        self.assertEqual(result["vendor_name"], "WeWork")
        self.assertEqual(result["amount"], Decimal("3200.00"))
        self.assertEqual(result["due_date"], D(2026, 9, 1))
        self.assertEqual(result["payment_ref"], "WW-88")

    def test_unreadable_payload_raises(self):
        with self.assertRaises(ValueError):
            self.service.decode(payload="@@@@")

    def test_uncoercible_amount_loses_its_detected_flag(self):
        result = self.service.decode(
            payload="SWAYP:vendor=WeWork;amount=not-a-number"
        )

        self.assertIsNone(result["amount"])
        self.assertNotIn("amount", result["provenance"])

    def test_it_shares_the_vendor_parser(self):
        """One code path — the bill service must not re-parse (E4-S7 AC)."""
        from apps.vendors.services.qr_decoder import QRDecodeService

        self.assertIsInstance(self.service.decoder, QRDecodeService)

        payload = "SWAYP:vendor=WeWork;ref=ABCD1234"

        self.assertEqual(
            self.service.decode(payload=payload)["payment_ref"],
            QRDecodeService().decode_payload(payload)["payment_ref"],
        )


class InvoiceTests(BillFixtureMixin, TestCase):

    def test_invoice_renders_from_bill_fields(self):
        self.occurrence(self.bill, D(2026, 2, 15))

        response = self.client.get(
            f"/api/v1/bills/{self.bill.id}/invoice"
        )
        data = response.data["data"]

        self.assertEqual(response.status_code, 200)
        self.assertEqual(data["vendor_name"], "WeWork")
        self.assertEqual(data["category"], "Commercial Rent")
        self.assertEqual(str(data["due_date"]), "2026-02-15")

    def test_invoice_carries_a_payment_reference(self):
        self.occurrence(self.bill, D(2026, 2, 15))

        data = self.client.get(
            f"/api/v1/bills/{self.bill.id}/invoice"
        ).data["data"]

        self.assertTrue(data["payment_reference"].startswith("SWAYP-"))
        self.assertIn("20260215", data["payment_reference"])

    def test_an_existing_payment_reference_wins(self):
        occurrence = self.occurrence(self.bill, D(2026, 2, 15))
        occurrence.payment_reference = "MOOV-TX-4417"
        occurrence.save(update_fields=["payment_reference"])

        data = self.client.get(
            f"/api/v1/bills/{self.bill.id}/invoice"
        ).data["data"]

        self.assertEqual(data["payment_reference"], "MOOV-TX-4417")

    def test_the_invoice_qr_round_trips_through_the_shared_parser(self):
        occurrence = self.occurrence(self.bill, D(2026, 2, 15))

        payload = InvoiceService().qr_payload(self.bill, occurrence)
        decoded = BillQRService().decode(payload=payload)

        self.assertEqual(decoded["vendor_name"], "WeWork")
        self.assertEqual(decoded["due_date"], D(2026, 2, 15))


class BillQRIdTests(TestCase):
    """BILLS-2: the decode answers with ids the wizard can use, and an
    unreadable QR fails in the standard envelope on both QR routes."""

    URL = "/api/v1/bills/qr/decode"

    def setUp(self):
        self.user = User.objects.create_user(
            email="qr-ids@example.com", password="Sw@yp-Test-1"
        )
        self.rent = BillCategory.objects.create(
            name="Commercial Rent", icon="https://e.com/i.png", color="#111"
        )
        self.client = APIClient()
        self.client.force_authenticate(user=self.user)

    def decode(self, payload):
        return self.client.post(self.URL, {"payload": payload}, format="json")

    def test_a_saved_vendor_is_matched_and_lends_its_category(self):
        vendor = Vendor.objects.create(
            user=self.user, name="WeWork", category=self.rent
        )

        data = self.decode("SWAYP:vendor=wework;amount=3200.00").json()["data"]

        self.assertEqual(data["vendor_id"], str(vendor.id))
        self.assertEqual(data["category_id"], str(self.rent.id))
        self.assertEqual(data["amount"], "3200.00")

    def test_an_unknown_vendor_is_null_not_invented(self):
        data = self.decode("SWAYP:vendor=Nobody;amount=10.00").json()["data"]

        self.assertIsNone(data["vendor_id"])
        self.assertEqual(Vendor.objects.count(), 0)

    def test_another_accounts_vendor_is_not_matched(self):
        stranger = User.objects.create_user(
            email="stranger@example.com", password="Sw@yp-Test-1"
        )
        Vendor.objects.create(user=stranger, name="WeWork", category=self.rent)

        data = self.decode("SWAYP:vendor=WeWork;amount=1.00").json()["data"]

        self.assertIsNone(data["vendor_id"])

    def test_unreadable_is_the_standard_envelope_on_both_routes(self):
        for url in (self.URL, "/api/v1/vendors/qr/decode"):
            with self.subTest(url=url):
                response = self.client.post(
                    url, {"payload": "@@@@"}, format="json"
                )

                self.assertEqual(response.status_code, 422)
                body = response.json()
                self.assertIs(body["success"], False)
                self.assertIn("message", body)
                self.assertNotIn("detail", body)


class BillDetailIdsTests(BillFixtureMixin, TestCase):
    """BILLS-5: the detail carries the ids an edit screen needs, the next
    occurrence to act on, and money as strings."""

    def detail(self):
        return self.client.get(f"/api/v1/bills/{self.bill.id}/details").json()[
            "data"
        ]

    def test_the_ids_are_there(self):
        method = VendorPaymentMethod.objects.create(
            vendor=self.vendor,
            method_type="ACH",
            provider="MOOV",
            provider_token="pm_x",
            account_last4="4821",
            account_holder_name="WeWork LLC",
            is_primary=True,
        )
        self.bill.payment_method = method
        self.bill.save(update_fields=["payment_method"])

        data = self.detail()

        self.assertEqual(data["vendor_id"], str(self.vendor.id))
        self.assertEqual(data["category_id"], str(self.category.id))
        self.assertEqual(data["payment_method_id"], str(method.id))
        self.assertEqual(data["account_ref"], "****4821")

    def test_next_occurrence_is_the_one_next_due_describes(self):
        self.occurrence(self.bill, D(2030, 1, 1), status=BillOccurrenceStatus.PAID)
        upcoming = self.occurrence(self.bill, D(2030, 2, 1))

        data = self.detail()

        self.assertEqual(data["next_occurrence"]["id"], str(upcoming.id))
        self.assertEqual(data["next_occurrence"]["status"], "UPCOMING")
        self.assertEqual(data["next_due"], "2030-02-01")

    def test_money_is_a_two_decimal_string_even_when_zero(self):
        data = self.detail()

        self.assertEqual(data["overdue_amount"], "0.00")
        self.assertEqual(data["total_paid"], "0.00")
        self.assertIsNone(data["last_paid_at"])
        self.assertIsNone(data["next_occurrence"])
        self.assertIsNone(data["payment_method_id"])
        self.assertIsNone(data["account_ref"])

    def test_last_paid_at_is_the_latest_payment(self):
        from django.utils import timezone

        paid = self.occurrence(
            self.bill, D(2026, 1, 15), status=BillOccurrenceStatus.PAID
        )
        paid.paid_at = timezone.now()
        paid.save(update_fields=["paid_at"])

        data = self.detail()

        self.assertIsNotNone(data["last_paid_at"])
        self.assertEqual(data["total_paid"], "3200.00")
