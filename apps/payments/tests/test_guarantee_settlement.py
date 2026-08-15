"""Where a delivery guarantee is judged, and against what (E9-S4).

The guarantee was being settled at processor success against
``payment.estimated_arrival`` — the promise compared to itself, which is never
late. So no guarantee could ever be missed and no fee could ever auto-refund,
while the AC read as satisfied because the billing tests called
``settle_guarantee`` directly with a real late date.

Two things had to be true and neither was: the arrival must be a real observed
date, and it must be judged at arrival rather than at send.
"""

import datetime as dt
import json

from decimal import Decimal

from django.test import TestCase
from django.utils import timezone

from apps.banking.factories import BankAccountFactory, BankConnectionFactory
from apps.billing.factories import SubscriptionFactory
from apps.billing.models import FeeCharge, FeeKind, FeeState, Plan, PlanCode
from apps.billing.services.fee_service import FeeService
from apps.bills.factories import BillFactory, BillOccurrenceFactory
from apps.common.enums import PaymentRail, PaymentStatus
from apps.payments.factories import PaymentFactory
from apps.payments.services.execution_service import PaymentExecutionService
from apps.payments.services.webhook_service import parse_arrival
from apps.vendors.factories import VendorPaymentMethodFactory

D = dt.date


class ArrivalParsingTests(TestCase):

    def test_each_known_key_is_read(self):
        for key in ("arrived_at", "delivered_at", "effective_date",
                    "settled_at"):
            self.assertEqual(
                parse_arrival({key: "2026-09-04"}),
                D(2026, 9, 4),
                msg=f"{key} should be recognised",
            )

    def test_a_timestamp_is_truncated_to_its_date(self):
        self.assertEqual(
            parse_arrival({"arrived_at": "2026-09-04T17:22:01Z"}),
            D(2026, 9, 4),
        )

    def test_an_absent_date_is_none_rather_than_a_guess(self):
        self.assertIsNone(parse_arrival({"type": "transfer.completed"}))

    def test_an_unparseable_date_is_none(self):
        """A guarantee must not be judged against something that failed to
        parse; the caller falls back to today instead."""
        self.assertIsNone(parse_arrival({"arrived_at": "not-a-date"}))


class GuaranteeSettlementTests(TestCase):

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
        self.bill.payment_method = VendorPaymentMethodFactory(
            vendor=self.bill.vendor
        )
        self.bill.save(update_fields=["payment_method"])

    def check_payment(self, promised=D(2026, 9, 1)):
        occurrence = BillOccurrenceFactory(
            bill=self.bill, due_date=D(2026, 9, 1), amount="900.00"
        )
        payment = PaymentFactory(
            user=self.user,
            bill_occurrence=occurrence,
            rail=PaymentRail.CHECK,
            amount="900.00",
            initiated_date=D(2026, 8, 28),
            estimated_arrival=promised,
            expedited=True,
        )

        fee = FeeService().charge_for_payment(
            subscription=self.subscription, payment=payment, expedited=True
        )

        return payment, fee

    # --- the arrival has to be observed, not assumed ----------------------

    def test_a_late_arrival_refunds_the_fee(self):
        payment, fee = self.check_payment(promised=D(2026, 9, 1))

        FeeService().settle_guarantee(
            payment=payment, actual_arrival=D(2026, 9, 3)
        )

        fee.refresh_from_db()
        self.assertEqual(fee.state, FeeState.REFUNDED)
        self.assertEqual(fee.amount, Decimal("8.99"))

    def test_an_on_time_arrival_does_not_refund(self):
        payment, fee = self.check_payment(promised=D(2026, 9, 1))

        FeeService().settle_guarantee(
            payment=payment, actual_arrival=D(2026, 9, 1)
        )

        fee.refresh_from_db()
        self.assertEqual(fee.state, FeeState.PENDING)

    def test_settling_against_the_promise_itself_can_never_refund(self):
        """The exact shape of the bug: estimated_arrival was passed as the
        actual arrival, so the comparison was promise > promise."""
        payment, fee = self.check_payment(promised=D(2026, 9, 1))

        FeeService().settle_guarantee(
            payment=payment, actual_arrival=payment.estimated_arrival
        )

        fee.refresh_from_db()
        self.assertEqual(fee.state, FeeState.PENDING)

    # --- and it has to be judged at arrival, not at send ------------------

    def test_execution_does_not_settle_a_check(self):
        """At processor success a check has been mailed, not delivered.
        Judging it here passes a guarantee that has had no chance to break."""
        payment, fee = self.check_payment(promised=D(2026, 8, 1))

        # Promised in the past — the only reason this stays PENDING is that
        # execution correctly declines to judge a check at all.
        PaymentExecutionService()._settle_guarantee(payment)

        fee.refresh_from_db()
        self.assertEqual(fee.state, FeeState.PENDING)

    def test_execution_does_settle_same_day_ach(self):
        """Same-day settles the day it is confirmed, so confirmation here IS
        arrival and a late execution is a real miss."""
        occurrence = BillOccurrenceFactory(
            bill=self.bill, due_date=D(2026, 9, 1), amount="900.00"
        )
        payment = PaymentFactory(
            user=self.user,
            bill_occurrence=occurrence,
            rail=PaymentRail.ACH_SAMEDAY,
            amount="900.00",
            initiated_date=timezone.localdate(),
            # Promised yesterday, confirmed today: missed.
            estimated_arrival=timezone.localdate() - dt.timedelta(days=1),
        )
        fee = FeeCharge.objects.create(
            subscription=self.subscription,
            payment=payment,
            kind=FeeKind.SAME_DAY_ACH,
            amount=Decimal("4.99"),
            guaranteed_arrival=payment.estimated_arrival,
        )

        PaymentExecutionService()._settle_guarantee(payment)

        fee.refresh_from_db()
        self.assertEqual(fee.state, FeeState.REFUNDED)

    def test_the_customer_is_notified_of_the_refund(self):
        from apps.notifications.models import Notification

        payment, fee = self.check_payment(promised=D(2026, 9, 1))

        FeeService().settle_guarantee(
            payment=payment, actual_arrival=D(2026, 9, 9)
        )

        self.assertTrue(
            Notification.objects.filter(
                user=self.user, title="Fee refunded"
            ).exists()
        )

    def test_the_refund_is_idempotent(self):
        payment, fee = self.check_payment(promised=D(2026, 9, 1))

        for _ in range(3):
            FeeService().settle_guarantee(
                payment=payment, actual_arrival=D(2026, 9, 9)
            )

        fee.refresh_from_db()
        first = fee.refunded_at

        FeeService().settle_guarantee(
            payment=payment, actual_arrival=D(2026, 9, 9)
        )
        fee.refresh_from_db()

        self.assertEqual(fee.refunded_at, first)

    def test_a_check_overage_is_never_refunded_for_slowness(self):
        """It bought no speed promise, so there is nothing to miss."""
        occurrence = BillOccurrenceFactory(
            bill=self.bill, due_date=D(2026, 9, 1), amount="900.00"
        )
        payment = PaymentFactory(
            user=self.user,
            bill_occurrence=occurrence,
            rail=PaymentRail.CHECK,
            estimated_arrival=D(2026, 9, 1),
        )
        fee = FeeCharge.objects.create(
            subscription=self.subscription,
            payment=payment,
            kind=FeeKind.CHECK_OVERAGE,
            amount=Decimal("2.99"),
            guaranteed_arrival=None,
        )

        FeeService().settle_guarantee(
            payment=payment, actual_arrival=D(2026, 12, 1)
        )

        fee.refresh_from_db()
        self.assertEqual(fee.state, FeeState.PENDING)


class WebhookGuaranteeTests(TestCase):
    """The webhook is the arrival event, so it is where checks are judged."""

    def setUp(self):
        from apps.payments.tests.test_webhooks import sign

        self.sign = sign
        self.subscription = SubscriptionFactory(
            plan=Plan.objects.get(code=PlanCode.FOUNDING)
        )
        self.user = self.subscription.account

        self.bill = BillFactory(user=self.user, anchor_date=D(2026, 9, 1))
        occurrence = BillOccurrenceFactory(
            bill=self.bill, due_date=D(2026, 9, 1), amount="900.00"
        )
        self.payment = PaymentFactory(
            user=self.user,
            bill_occurrence=occurrence,
            rail=PaymentRail.CHECK,
            amount="900.00",
            status=PaymentStatus.PROCESSING,
            initiated_date=D(2026, 8, 28),
            estimated_arrival=D(2026, 9, 1),
            expedited=True,
        )
        self.fee = FeeService().charge_for_payment(
            subscription=self.subscription,
            payment=self.payment,
            expedited=True,
        )

    def post(self, payload):
        body = json.dumps(payload).encode()

        return self.client.post(
            "/webhooks/mock",
            data=body,
            content_type="application/json",
            HTTP_X_SWAYP_SIGNATURE=self.sign(body),
        )

    def completed(self, **extra):
        payload = {
            "id": f"evt_{extra.get('arrived_at', 'none')}",
            "type": "transfer.completed",
            "reference": self.payment.transaction_reference,
        }
        payload.update(extra)

        return self.post(payload)

    def test_a_late_arrival_reported_by_the_processor_refunds(self):
        response = self.completed(arrived_at="2026-09-04")

        self.assertEqual(response.status_code, 200)

        self.fee.refresh_from_db()
        self.assertEqual(self.fee.state, FeeState.REFUNDED)

    def test_an_on_time_arrival_does_not_refund(self):
        response = self.completed(arrived_at="2026-09-01")

        self.assertEqual(response.status_code, 200)

        self.fee.refresh_from_db()
        self.assertEqual(self.fee.state, FeeState.PENDING)

    def test_without_a_stated_date_today_is_used(self):
        """The webhook fires when the money lands, so today is honest."""
        # Promised yesterday; arriving today (no stated date) is one day late.
        self.fee.guaranteed_arrival = (
            timezone.localdate() - dt.timedelta(days=1)
        )
        self.fee.save(update_fields=["guaranteed_arrival"])

        self.completed()

        self.fee.refresh_from_db()
        self.assertEqual(self.fee.state, FeeState.REFUNDED)

    def test_without_a_stated_date_a_future_promise_is_not_missed(self):
        """Today cannot be late against a date that has not arrived."""
        self.completed()

        self.fee.refresh_from_db()
        self.assertEqual(self.fee.state, FeeState.PENDING)
