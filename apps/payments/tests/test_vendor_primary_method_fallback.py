"""A bill is paid by its vendor's primary method when it names none.

Every bill the bank scan imports starts without a payment method: the
importer creates a vendor out of a transaction description and has no routing
details for it. ``rails_for_bill`` read only ``bill.payment_method``, so those
bills quoted as unavailable on every rail and stayed that way for good —
adding ACH details to the vendor afterwards did not reach the bills already
imported against it, because nothing re-pointed them.

``POST /payments`` meanwhile created a payment for such a bill regardless:
``_assert_rails_fit`` compares a named rail against the allowed ones and skips
a bill that allows none. The user confirmed an authorization and the payment
reached execution with an empty destination token, failing there.
"""

import datetime as dt

from django.test import TestCase
from rest_framework.exceptions import ValidationError
from rest_framework.test import APIClient

from apps.banking.factories import BankAccountFactory, BankConnectionFactory
from apps.bills.factories import BillFactory, BillOccurrenceFactory
from apps.common.enums import BillSource, PaymentRail
from apps.payments.services.execution_service import PaymentExecutionService
from apps.payments.services.payment_create_service import PaymentCreateService
from apps.payments.services.quote_service import PaymentQuoteService
from apps.payments.services.rails import (
    method_for_bill,
    rail_for_bill,
    rails_for_bill,
)
from apps.vendors.factories import (
    UserFactory,
    VendorFactory,
    VendorPaymentMethodFactory,
)

DUE = dt.date(2026, 11, 20)


class MethodResolutionTests(TestCase):

    def setUp(self):
        self.user = UserFactory()
        self.vendor = VendorFactory(user=self.user, name="Con Edison")
        self.bill = BillFactory(
            user=self.user,
            vendor=self.vendor,
            source=BillSource.DETECTED,
            payment_method=None,
        )

    def test_an_imported_bill_uses_the_vendors_primary_method(self):
        primary = VendorPaymentMethodFactory(
            vendor=self.vendor, method_type="ACH", is_primary=True
        )

        self.assertEqual(method_for_bill(self.bill), primary)
        self.assertEqual(
            rails_for_bill(self.bill),
            (PaymentRail.ACH_STANDARD, PaymentRail.ACH_SAMEDAY),
        )
        self.assertEqual(rail_for_bill(self.bill), PaymentRail.ACH_STANDARD)

    def test_adding_the_method_later_is_enough(self):
        """The case that was permanently broken: the bill is imported first
        and the vendor is given details afterwards. Resolution happens at
        read time, so nothing has to re-point the bill."""
        self.assertEqual(rails_for_bill(self.bill), ())

        VendorPaymentMethodFactory(
            vendor=self.vendor, method_type="CHECK", is_primary=True
        )

        self.assertEqual(rails_for_bill(self.bill), (PaymentRail.CHECK,))

    def test_the_bills_own_method_still_wins(self):
        VendorPaymentMethodFactory(
            vendor=self.vendor, method_type="ACH", is_primary=True
        )
        own = VendorPaymentMethodFactory(
            vendor=self.vendor, method_type="CHECK", is_primary=False
        )
        self.bill.payment_method = own
        self.bill.save(update_fields=["payment_method"])

        self.assertEqual(method_for_bill(self.bill), own)
        self.assertEqual(rails_for_bill(self.bill), (PaymentRail.CHECK,))

    def test_a_vendor_with_no_method_resolves_to_nothing(self):
        self.assertIsNone(method_for_bill(self.bill))
        self.assertEqual(rails_for_bill(self.bill), ())

    def test_a_non_primary_method_alone_is_not_used(self):
        """Primary means "the one to use"; a method not marked primary was
        not chosen for this vendor."""
        VendorPaymentMethodFactory(
            vendor=self.vendor, method_type="ACH", is_primary=False
        )

        self.assertIsNone(method_for_bill(self.bill))


class QuoteTests(TestCase):

    def setUp(self):
        self.user = UserFactory()
        self.vendor = VendorFactory(user=self.user, name="Starbucks")
        self.bill = BillFactory(
            user=self.user,
            vendor=self.vendor,
            source=BillSource.DETECTED,
            payment_method=None,
        )
        self.occurrence = BillOccurrenceFactory(
            bill=self.bill, due_date=DUE, amount="4.33"
        )

    def quote(self):
        return PaymentQuoteService().quote(
            user=self.user, occurrence_ids=[str(self.occurrence.id)]
        )["occurrences"][0]

    def test_the_reason_names_the_provider_and_what_to_do(self):
        """Shown to the user verbatim by the client, so "this bill has no
        payment method saved" told them neither which payee nor what to do."""
        reasons = {row["unavailable_reason"] for row in self.quote()["rails"]}

        self.assertEqual(len(reasons), 1)
        reason = reasons.pop()
        self.assertIn("Starbucks", reason)
        self.assertIn("Add how to pay this provider", reason)

    def test_a_rail_mismatch_does_not_crash_on_a_vendor_method(self):
        """``allowed`` is non-empty because the *vendor* has a method while
        the bill's own field is None — the mismatch branch read
        ``bill.payment_method.method_type`` and raised AttributeError, a 500
        on the pay screen for every imported bill that had become payable."""
        VendorPaymentMethodFactory(
            vendor=self.vendor, method_type="ACH", is_primary=True
        )

        rails = {row["rail"]: row for row in self.quote()["rails"]}

        self.assertTrue(rails[PaymentRail.ACH_STANDARD]["available"])
        self.assertFalse(rails[PaymentRail.CHECK]["available"])
        self.assertEqual(
            rails[PaymentRail.CHECK]["unavailable_reason"],
            "This vendor is paid by ACH.",
        )

    def test_it_becomes_payable_once_the_vendor_has_a_method(self):
        VendorPaymentMethodFactory(
            vendor=self.vendor, method_type="ACH", is_primary=True
        )

        row = self.quote()

        self.assertEqual(row["default_rail"], PaymentRail.ACH_STANDARD)
        self.assertTrue(
            any(r["available"] for r in row["rails"]),
            msg="no rail available for a vendor that can be paid",
        )


class CreateRefusalTests(TestCase):

    def setUp(self):
        self.user = UserFactory()
        self.vendor = VendorFactory(user=self.user, name="McDonald's")
        self.bill = BillFactory(
            user=self.user,
            vendor=self.vendor,
            source=BillSource.DETECTED,
            payment_method=None,
        )
        self.occurrence = BillOccurrenceFactory(
            bill=self.bill, due_date=DUE, amount="12.00"
        )
        connection = BankConnectionFactory(user=self.user)
        BankAccountFactory(connection=connection)
        self.client = APIClient()
        self.client.force_authenticate(user=self.user)

    def test_it_refuses_rather_than_reserving_a_doomed_payment(self):
        with self.assertRaises(ValidationError) as ctx:
            PaymentCreateService().create(
                user=self.user, occurrence_ids=[str(self.occurrence.id)]
            )

        self.assertIn("McDonald's", str(ctx.exception))

    def test_the_endpoint_answers_400_and_names_the_provider(self):
        response = self.client.post(
            "/api/v1/payments",
            {"occurrence_ids": [str(self.occurrence.id)]},
            format="json",
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn("McDonald's", str(response.json()["errors"]))

    def test_nothing_is_created(self):
        """A refusal that still reserved the bill would leave the occurrence
        SCHEDULED and stop its reminders."""
        from apps.common.enums import BillOccurrenceStatus
        from apps.payments.models import Payment

        self.client.post(
            "/api/v1/payments",
            {"occurrence_ids": [str(self.occurrence.id)]},
            format="json",
        )
        self.occurrence.refresh_from_db()

        self.assertEqual(Payment.objects.filter(user=self.user).count(), 0)
        self.assertNotEqual(
            self.occurrence.status, BillOccurrenceStatus.SCHEDULED
        )

    def test_a_payable_bill_is_unaffected(self):
        VendorPaymentMethodFactory(
            vendor=self.vendor, method_type="ACH", is_primary=True
        )

        response = self.client.post(
            "/api/v1/payments",
            {"occurrence_ids": [str(self.occurrence.id)]},
            format="json",
        )

        self.assertEqual(response.status_code, 201)


class ExecutionTests(TestCase):

    def test_the_destination_is_the_effective_method(self):
        """Execution sends to the method's token. Reading only the bill's own
        field meant a bill relying on its vendor's primary method was sent to
        an empty destination."""
        user = UserFactory()
        vendor = VendorFactory(user=user, name="Con Edison")
        VendorPaymentMethodFactory(
            vendor=vendor,
            method_type="ACH",
            is_primary=True,
            provider_token="dest-token-abc",
        )
        bill = BillFactory(
            user=user, vendor=vendor, source=BillSource.DETECTED,
            payment_method=None,
        )
        occurrence = BillOccurrenceFactory(
            bill=bill, due_date=DUE, amount="214.00"
        )
        connection = BankConnectionFactory(user=user)
        BankAccountFactory(connection=connection)

        created = PaymentCreateService().create(
            user=user, occurrence_ids=[str(occurrence.id)]
        )
        payment = created["payments"][0]

        self.assertEqual(
            PaymentExecutionService()._destination_token(payment),
            "dest-token-abc",
        )
