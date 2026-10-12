"""A bill created without a payment method uses the vendor's primary one.

``payment_method`` is optional on ``POST /bills/create`` and the add-bill
wizard has no step that sets it, so bills arrived with ``payment_method=None``
— and ``rails_for_bill`` returns no rails for such a bill, which makes
``POST /payments/quote`` report every rail as unavailable ("This bill has no
payment method saved."). Every bill created through the app was therefore
impossible to pay, and nothing said so until the user reached Pay.

``one_primary_method_per_vendor`` is what makes the default unambiguous.
"""

import datetime as dt

from django.test import TestCase
from rest_framework.test import APIClient

from apps.bills.models.bill import Bill
from apps.payments.services.rails import rail_for_bill, rails_for_bill
from apps.vendors.factories import (
    BillCategoryFactory,
    UserFactory,
    VendorFactory,
    VendorPaymentMethodFactory,
)

URL = "/api/v1/bills/create"


class PaymentMethodDefaultTests(TestCase):

    def setUp(self):
        self.user = UserFactory()
        self.client = APIClient()
        self.client.force_authenticate(user=self.user)
        self.category = BillCategoryFactory()
        self.vendor = VendorFactory(user=self.user, category=self.category)

    def body(self, **extra):
        payload = {
            "vendor": str(self.vendor.id),
            "category": str(self.category.id),
            "amount": "142.50",
            "frequency": "MONTHLY",
            "anchor_date": (
                dt.date.today() + dt.timedelta(days=7)
            ).isoformat(),
        }
        payload.update(extra)
        return payload

    def test_the_vendors_primary_method_is_used_when_none_is_given(self):
        primary = VendorPaymentMethodFactory(
            vendor=self.vendor, method_type="ACH", is_primary=True
        )

        response = self.client.post(URL, self.body(), format="json")

        self.assertEqual(response.status_code, 201)
        bill = Bill.objects.get(id=response.json()["data"]["id"])
        self.assertEqual(bill.payment_method_id, primary.id)

    def test_such_a_bill_is_payable(self):
        """The property that actually matters: the quote offers a rail."""
        VendorPaymentMethodFactory(
            vendor=self.vendor, method_type="ACH", is_primary=True
        )

        response = self.client.post(URL, self.body(), format="json")
        bill = Bill.objects.get(id=response.json()["data"]["id"])

        self.assertTrue(rails_for_bill(bill))
        self.assertEqual(rail_for_bill(bill), "ACH_STANDARD")

    def test_an_explicit_method_still_wins(self):
        VendorPaymentMethodFactory(
            vendor=self.vendor, method_type="ACH", is_primary=True
        )
        chosen = VendorPaymentMethodFactory(
            vendor=self.vendor, method_type="CHECK", is_primary=False
        )

        response = self.client.post(
            URL, self.body(payment_method=str(chosen.id)), format="json"
        )

        self.assertEqual(response.status_code, 201)
        bill = Bill.objects.get(id=response.json()["data"]["id"])
        self.assertEqual(bill.payment_method_id, chosen.id)

    def test_a_vendor_with_no_method_leaves_the_bill_without_one(self):
        """Not an error: Swayp has no routing details for this payee yet. The
        bill is created and the quote says why it cannot be paid."""
        response = self.client.post(URL, self.body(), format="json")

        self.assertEqual(response.status_code, 201)
        bill = Bill.objects.get(id=response.json()["data"]["id"])
        self.assertIsNone(bill.payment_method_id)
        self.assertEqual(rails_for_bill(bill), ())

    def test_a_method_belonging_to_another_vendor_is_still_refused(self):
        other = VendorFactory(user=self.user, category=self.category)
        theirs = VendorPaymentMethodFactory(
            vendor=other, method_type="ACH", is_primary=True
        )

        response = self.client.post(
            URL, self.body(payment_method=str(theirs.id)), format="json"
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn("payment_method", response.json()["errors"])
