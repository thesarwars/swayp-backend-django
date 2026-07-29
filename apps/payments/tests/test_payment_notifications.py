"""E8-S3 — the payments call-sites now emit typed events.

Every notification the money paths produce is asserted on its type and on the
deep-link payload it carries, because the type is what a client routes on and
the payload is what it deep-links with. The two events the epic assigns to the
webhook consumer — PAYMENT_ARRIVED and the processor-driven PAYMENT_FAILED —
had no producer at all before this story, so they are asserted from the
webhook in.
"""

import datetime as dt
from decimal import Decimal
from unittest import mock

from django.test import TestCase, override_settings

from apps.banking.factories import BankAccountFactory
from apps.bills.factories import (
    BillOccurrenceFactory,
    StandingAuthorizationFactory,
)
from apps.common.dates import today_eastern
from apps.common.enums import (
    AutopayMode,
    BillOccurrenceStatus,
    NotificationType,
    PaymentStatus,
)
from apps.notifications.models import Notification
from apps.payments.factories import PaymentFactory
from apps.payments.models import Payment
from apps.payments.services.autopay_service import AutopayService
from apps.payments.services.execution_service import PaymentExecutionService
from apps.payments.services.payment_service import PaymentService
from apps.payments.services.webhook_service import (
    RESULT_APPLIED,
    WebhookService,
)
from apps.vendors.factories import (
    UserFactory,
    VendorFactory,
    VendorPaymentMethodFactory,
)
from integrations.money_movement.mock import MockMoneyMovementProvider

#: The mock provider fails any amount ending in .01 with NSF.
NSF_AMOUNT = Decimal("3200.01")

_DELAY = "apps.notifications.channels.email.send_notification_email.delay"
_PROVIDER = "apps.notifications.tasks.get_messaging_provider"


class PaymentNotificationTests(TestCase):

    def setUp(self):
        MockMoneyMovementProvider.reset()
        self.user = UserFactory()
        self.vendor = VendorFactory(user=self.user, name="WeWork")
        self.occurrence = BillOccurrenceFactory(
            bill__user=self.user,
            bill__vendor=self.vendor,
            due_date=today_eastern() + dt.timedelta(days=4),
            amount=Decimal("3200.00"),
            status=BillOccurrenceStatus.SCHEDULED,
        )

    def _payment(self, **kwargs):
        return PaymentFactory(
            user=self.user,
            vendor=self.vendor,
            bill_occurrence=self.occurrence,
            **kwargs,
        )

    def test_payment_failure_emits_payment_failed_with_deep_link_context(
        self,
    ):
        executed = self._payment(
            amount=NSF_AMOUNT,
            total=NSF_AMOUNT,
            status=PaymentStatus.PROCESSING,
        )

        PaymentExecutionService().execute(executed.id)

        engine_alert = Notification.objects.get(
            metadata__payment_id=str(executed.id)
        )

        self.assertEqual(engine_alert.type, NotificationType.PAYMENT_FAILED)
        self.assertEqual(engine_alert.title, "Payment failed")
        self.assertEqual(
            engine_alert.metadata["reference"], executed.transaction_reference
        )
        self.assertEqual(
            engine_alert.metadata["occurrence_id"], str(self.occurrence.id)
        )
        self.assertEqual(engine_alert.metadata["reason"], "NSF")
        self.assertIn("NSF", engine_alert.message)

        marked = self._payment(status=PaymentStatus.PROCESSING)

        PaymentService().mark_failed(user=self.user, payment_id=marked.id)

        manual_alert = Notification.objects.get(
            metadata__payment_id=str(marked.id)
        )

        self.assertEqual(manual_alert.type, NotificationType.PAYMENT_FAILED)
        self.assertEqual(
            manual_alert.metadata["reference"], marked.transaction_reference
        )
        self.assertEqual(
            manual_alert.metadata["occurrence_id"], str(self.occurrence.id)
        )
        self.assertEqual(manual_alert.metadata["reason"], "Marked failed")

    def test_processor_failure_webhook_emits_payment_failed(self):
        """The asynchronous-rail case the epic assigns to the webhook.

        On a rail that settles later, this is the only place a failure is
        ever learned about — before this story it emitted nothing.
        """
        payment = self._payment(status=PaymentStatus.PROCESSING)

        result = WebhookService().handle(
            processor="MOCK",
            event_id="evt-failed-1",
            event_type="transfer.failed",
            payload={
                "reference": payment.transaction_reference,
                "reason": "R01_NSF",
            },
        )

        self.assertEqual(result, RESULT_APPLIED)

        notification = Notification.objects.get()

        self.assertEqual(notification.type, NotificationType.PAYMENT_FAILED)
        self.assertEqual(
            notification.metadata["payment_id"], str(payment.id)
        )
        self.assertEqual(
            notification.metadata["occurrence_id"], str(self.occurrence.id)
        )
        self.assertIn("R01_NSF", notification.message)

    def test_ach_return_emits_payment_reversed(self):
        payment = self._payment(status=PaymentStatus.SUCCESSFUL)

        result = WebhookService().handle(
            processor="MOCK",
            event_id="evt-returned-1",
            event_type="transfer.returned",
            payload={"reference": payment.transaction_reference},
        )

        self.assertEqual(result, RESULT_APPLIED)

        notification = Notification.objects.get()

        self.assertEqual(notification.type, NotificationType.PAYMENT_REVERSED)
        # Copy preserved byte-for-byte across the migration onto notify().
        self.assertEqual(notification.title, "Payment returned")
        self.assertEqual(
            notification.message,
            f"{payment.transaction_reference} was returned by the bank. "
            "The bill is outstanding again.",
        )
        self.assertEqual(
            notification.metadata["payment_id"], str(payment.id)
        )

    def test_settlement_webhook_emits_payment_arrived(self):
        """Only reachable on a rail that had not already settled inline."""
        payment = self._payment(status=PaymentStatus.PROCESSING)

        result = WebhookService().handle(
            processor="MOCK",
            event_id="evt-completed-1",
            event_type="transfer.completed",
            payload={"reference": payment.transaction_reference},
        )

        self.assertEqual(result, RESULT_APPLIED)

        notification = Notification.objects.get()

        self.assertEqual(notification.type, NotificationType.PAYMENT_ARRIVED)
        self.assertEqual(
            notification.message,
            f"{payment.transaction_reference} to WeWork completed.",
        )

    def test_manual_success_stays_on_the_generic_payment_type(self):
        """SUCCESSFUL at the processor is not arrival.

        A check is five business days from sent to arrived — which is why
        estimated_arrival exists — so labelling this PAYMENT_ARRIVED would be
        a lie on every rail but NETWORK.
        """
        payment = self._payment(status=PaymentStatus.PROCESSING)

        PaymentService().mark_successful(
            user=self.user, payment_id=payment.id
        )

        notification = Notification.objects.get()

        self.assertEqual(notification.type, NotificationType.PAYMENT)
        self.assertEqual(notification.title, "Payment successful")
        self.assertEqual(
            notification.message,
            f"Payment {payment.transaction_reference} completed successfully.",
        )
        self.assertEqual(
            notification.metadata["occurrence_id"], str(self.occurrence.id)
        )


class AutopayNotificationTests(TestCase):

    def setUp(self):
        MockMoneyMovementProvider.reset()
        self.user = UserFactory()
        self.vendor = VendorFactory(user=self.user, name="WeWork")
        VendorPaymentMethodFactory(vendor=self.vendor)
        BankAccountFactory(connection__user=self.user)
        self.today = today_eastern()
        self.occurrence = BillOccurrenceFactory(
            bill__user=self.user,
            bill__vendor=self.vendor,
            bill__autopay_mode=AutopayMode.AUTO,
            # Comfortably inside the ACH lead window, whatever weekday the
            # suite runs on.
            due_date=self.today,
            amount=Decimal("3200.00"),
        )

    def test_autopay_run_emits_autopay_executed(self):
        StandingAuthorizationFactory(bill=self.occurrence.bill)

        AutopayService().run(today=self.today)

        notification = Notification.objects.get(
            type=NotificationType.AUTOPAY_EXECUTED
        )

        self.assertEqual(notification.title, "Autopay started for WeWork")
        self.assertEqual(
            notification.metadata["occurrence_id"], str(self.occurrence.id)
        )
        self.assertEqual(
            notification.metadata["bill_id"], str(self.occurrence.bill_id)
        )
        self.assertIn("payment_id", notification.metadata)

    def test_autopay_notification_never_claims_a_payment_that_then_failed(
        self,
    ):
        """The event fires at initiation, so its copy may not claim arrival.

        AUTOPAY_EXECUTED is written inside _pay, before the transfer is even
        attempted — execute_payment runs from an on_commit callback. Here the
        transfer then comes back NSF, and the user ends up holding both rows.
        A past-tense "Autopay paid WeWork" alongside "Payment failed" is the
        kind of small lie that ends in a support ticket.
        """
        self.occurrence.amount = NSF_AMOUNT
        self.occurrence.save(update_fields=["amount", "updated_at"])
        StandingAuthorizationFactory(bill=self.occurrence.bill)

        with self.captureOnCommitCallbacks(execute=True):
            AutopayService().run(today=self.today)

        started = Notification.objects.get(
            type=NotificationType.AUTOPAY_EXECUTED
        )

        for claim in ("paid", "sent "):
            self.assertNotIn(claim, started.title.lower())
            self.assertNotIn(claim, started.message.lower())

        self.assertEqual(
            started.message,
            f"Autopay is sending {NSF_AMOUNT} to WeWork for the bill due "
            f"{self.occurrence.due_date}. We'll let you know when it lands.",
        )

        # The payment really did fail, which is what makes the wording matter.
        failure = Notification.objects.get(
            type=NotificationType.PAYMENT_FAILED
        )
        self.assertIn("NSF", failure.message)

        payment = Payment.objects.get(bill_occurrence=self.occurrence)
        self.assertEqual(payment.status, PaymentStatus.FAILED)

    def test_autopay_without_authorization_alerts_without_claiming_a_payment(
        self,
    ):
        AutopayService().run(today=self.today)

        notification = Notification.objects.get()

        # SYSTEM, not AUTOPAY_EXECUTED: autopay did not run. This is a wire
        # value change from "PAYMENT" and the FE routes on it.
        self.assertEqual(notification.type, NotificationType.SYSTEM)
        self.assertEqual(notification.title, "Autopay needs your attention")
        self.assertEqual(
            notification.metadata["bill_id"], str(self.occurrence.bill_id)
        )


@override_settings(NOTIFICATION_EMAIL_ENABLED=True)
class NotificationOutageDoesNotBreakTheMoneyPathTests(TestCase):
    """A broken delivery pipe must not read as a failed payment.

    execution_service settles money and then notifies, inside the same
    transaction. If either half of the email path could raise from there, an
    SMTP outage or a dead broker would roll a settled payment back — which is
    why deliver() defers to on_commit and the task swallows everything.
    """

    def setUp(self):
        MockMoneyMovementProvider.reset()
        self.user = UserFactory()
        self.vendor = VendorFactory(user=self.user, name="WeWork")
        self.occurrence = BillOccurrenceFactory(
            bill__user=self.user,
            bill__vendor=self.vendor,
            due_date=today_eastern() + dt.timedelta(days=4),
            amount=Decimal("3200.00"),
            status=BillOccurrenceStatus.SCHEDULED,
        )
        self.payment = PaymentFactory(
            user=self.user,
            vendor=self.vendor,
            bill_occurrence=self.occurrence,
            status=PaymentStatus.PROCESSING,
        )

    def _assert_payment_settled(self):
        self.payment.refresh_from_db()

        self.assertEqual(self.payment.status, PaymentStatus.SUCCESSFUL)
        self.assertEqual(
            Notification.objects.get(
                metadata__payment_id=str(self.payment.id)
            ).type,
            NotificationType.PAYMENT,
        )

    def test_a_dead_broker_does_not_break_payment_execution(self):
        dead_broker = mock.Mock(side_effect=OSError("broker unreachable"))

        with mock.patch(_DELAY, dead_broker):
            with self.captureOnCommitCallbacks(execute=True):
                PaymentExecutionService().execute(self.payment.id)

        dead_broker.assert_called_once()
        self._assert_payment_settled()

    def test_a_raising_messaging_provider_does_not_break_execution(self):
        with mock.patch(
            _PROVIDER, side_effect=RuntimeError("mail server is down")
        ):
            with self.captureOnCommitCallbacks(execute=True):
                PaymentExecutionService().execute(self.payment.id)

        self._assert_payment_settled()
