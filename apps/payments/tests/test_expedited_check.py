"""Expedited check, end to end (E9-S3 · $8.99, all plans).

The fee existed and was tested at the service layer, but nothing could reach
it: ``POST /payments/`` had no ``expedited`` field, and the execution hook read
the flag out of ``failure_detail`` — a JSONField for failure diagnostics that
nothing ever wrote that key into. So the charge was unreachable in production
and the check never actually went faster.

These tests cover the path a customer travels, not the service call.
"""

import datetime as dt

from decimal import Decimal

from django.test import TestCase
from rest_framework.test import APIClient

from apps.banking.factories import BankAccountFactory, BankConnectionFactory
from apps.billing.factories import SubscriptionFactory
from apps.billing.models import FeeCharge, FeeKind, Plan, PlanCode
from apps.bills.factories import BillFactory, BillOccurrenceFactory
from apps.common.dates import estimated_arrival
from apps.common.enums import PaymentRail
from apps.payments.models import Payment
from apps.payments.services.execution_service import PaymentExecutionService
from apps.payments.services.payment_create_service import PaymentCreateService
from apps.vendors.factories import VendorPaymentMethodFactory

D = dt.date


class ExpeditedCheckTests(TestCase):

    def setUp(self):
        self.subscription = SubscriptionFactory(
            plan=Plan.objects.get(code=PlanCode.FOUNDING)
        )
        self.user = self.subscription.account

        connection = BankConnectionFactory(user=self.user)
        BankAccountFactory(
            connection=connection, is_default_funding_source=True
        )

        self.bill = BillFactory(user=self.user, anchor_date=D(2026, 9, 1))
        # A check method: these tests pay by check, and a rail has to suit
        # the bill's saved method (PAY-5).
        self.bill.payment_method = VendorPaymentMethodFactory(
            vendor=self.bill.vendor, check=True
        )
        self.bill.save(update_fields=["payment_method"])

        self.client = APIClient()
        self.client.force_authenticate(user=self.user)

    def occurrence(self, due=D(2026, 9, 1)):
        return BillOccurrenceFactory(
            bill=self.bill, due_date=due, amount="900.00"
        )

    def create(self, **kwargs):
        payload = {
            "occurrence_ids": [str(self.occurrence().id)],
            "rail": PaymentRail.CHECK,
        }
        payload.update(kwargs)

        return self.client.post("/api/v1/payments", payload, format="json")

    # --- the API accepts it ----------------------------------------------

    def test_the_create_endpoint_accepts_expedited(self):
        response = self.create(expedited=True)

        self.assertEqual(response.status_code, 201)

        payment = Payment.objects.get(
            id=response.data["data"]["payments"][0]["id"]
        )
        self.assertTrue(payment.expedited)

    def test_expedited_is_visible_on_the_payment(self):
        """The customer paid for it, so it has to be readable back."""
        response = self.create(expedited=True)

        self.assertTrue(response.data["data"]["payments"][0]["expedited"])

    def test_payments_are_not_expedited_by_default(self):
        response = self.create()

        payment = Payment.objects.get(
            id=response.data["data"]["payments"][0]["id"]
        )
        self.assertFalse(payment.expedited)

    def test_expedited_is_refused_on_a_non_check_rail(self):
        """Refused, not ignored — silently downgrading takes the money's
        worth of speed away while still reading as success."""
        response = self.create(
            rail=PaymentRail.ACH_STANDARD, expedited=True
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn("expedited", response.data["errors"])

    # --- it buys something ------------------------------------------------

    def test_expedited_arrives_sooner_than_a_standard_check(self):
        """Otherwise the $8.99 sells a promise identical to the free one."""
        sent = D(2026, 8, 3)

        standard = estimated_arrival(sent, PaymentRail.CHECK)
        fast = estimated_arrival(sent, PaymentRail.CHECK, expedited=True)

        self.assertLess(fast, standard)

    def test_only_the_check_rail_has_an_expedited_transit(self):
        sent = D(2026, 8, 3)

        for rail in (
            PaymentRail.ACH_STANDARD,
            PaymentRail.ACH_SAMEDAY,
            PaymentRail.NETWORK,
        ):
            self.assertEqual(
                estimated_arrival(sent, rail, expedited=True),
                estimated_arrival(sent, rail),
                msg=f"{rail} should have no expedited tier",
            )

    def test_the_stored_arrival_reflects_the_expedited_transit(self):
        response = self.create(expedited=True)

        payment = Payment.objects.get(
            id=response.data["data"]["payments"][0]["id"]
        )

        self.assertEqual(
            payment.estimated_arrival,
            estimated_arrival(
                payment.initiated_date, PaymentRail.CHECK, expedited=True
            ),
        )

    # --- and it bills -----------------------------------------------------

    def execute(self, payment):
        PaymentExecutionService()._charge_fee(payment)

        return FeeCharge.objects.filter(payment=payment)

    def test_an_expedited_check_is_charged_8_99(self):
        response = self.create(expedited=True)
        payment = Payment.objects.get(
            id=response.data["data"]["payments"][0]["id"]
        )

        fees = self.execute(payment)

        self.assertEqual(fees.count(), 1)
        self.assertEqual(fees.first().kind, FeeKind.EXPEDITED_CHECK)
        self.assertEqual(fees.first().amount, Decimal("8.99"))

    def test_expedited_bills_even_with_free_checks_remaining(self):
        """It is a separate product, not an overage."""
        response = self.create(expedited=True)
        payment = Payment.objects.get(
            id=response.data["data"]["payments"][0]["id"]
        )

        self.execute(payment)

        # Founding includes two free checks and none has been consumed.
        self.assertEqual(
            FeeCharge.objects.filter(
                kind=FeeKind.CHECK_OVERAGE
            ).count(),
            0,
        )
        self.assertEqual(
            FeeCharge.objects.filter(
                kind=FeeKind.EXPEDITED_CHECK
            ).count(),
            1,
        )

    def test_a_standard_check_inside_the_allotment_is_still_free(self):
        response = self.create()
        payment = Payment.objects.get(
            id=response.data["data"]["payments"][0]["id"]
        )

        self.assertEqual(self.execute(payment).count(), 0)

    def test_the_expedited_fee_carries_a_guarantee(self):
        """It is refundable under E9-S4; a check overage is not."""
        response = self.create(expedited=True)
        payment = Payment.objects.get(
            id=response.data["data"]["payments"][0]["id"]
        )

        fee = self.execute(payment).first()

        self.assertIsNotNone(fee.guaranteed_arrival)
        self.assertTrue(fee.is_refundable)

    def test_the_guarantee_is_the_date_the_customer_was_shown(self):
        """The regression: the fee recomputed the arrival on the standard
        transit, guaranteeing the 4th while the customer saw the 1st. A check
        three days late by the only date they ever saw would not refund."""
        response = self.create(expedited=True)
        shown = response.data["data"]["payments"][0]["estimated_arrival"]

        payment = Payment.objects.get(
            id=response.data["data"]["payments"][0]["id"]
        )
        fee = self.execute(payment).first()

        self.assertEqual(str(fee.guaranteed_arrival), shown)

    def test_a_late_expedited_check_refunds_against_the_shown_date(self):
        from apps.billing.services.fee_service import FeeService

        response = self.create(expedited=True)
        payment = Payment.objects.get(
            id=response.data["data"]["payments"][0]["id"]
        )
        fee = self.execute(payment).first()

        FeeService().settle_guarantee(
            payment=payment,
            actual_arrival=fee.guaranteed_arrival + dt.timedelta(days=1),
        )

        fee.refresh_from_db()
        self.assertEqual(fee.state, "REFUNDED")

    def test_the_service_no_longer_reads_the_flag_from_failure_detail(self):
        """The regression: failure_detail is for diagnostics, and nothing
        wrote this key, so the fee was unreachable."""
        payment = PaymentCreateService().create(
            user=self.user,
            occurrence_ids=[self.occurrence(D(2026, 10, 1)).id],
            rail=PaymentRail.CHECK,
            expedited=False,
        )["payments"][0]

        payment.failure_detail = {"expedited": True}
        payment.save(update_fields=["failure_detail"])

        fees = self.execute(payment)

        self.assertFalse(
            fees.filter(kind=FeeKind.EXPEDITED_CHECK).exists()
        )
