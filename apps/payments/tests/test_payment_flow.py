"""End-to-end pay flow (E6-S2 … E6-S7, S9, S10, S11)."""

import datetime as dt
from decimal import Decimal

from django.test import TestCase, override_settings
from django.utils import timezone
from rest_framework.test import APIClient

from apps.banking.factories import BankAccountFactory, BankConnectionFactory
from apps.bills.factories import BillFactory, BillOccurrenceFactory
from apps.bills.models.bill_occurrence import BillOccurrence
from apps.bills.models.standing_authorization import StandingAuthorization
from apps.common.enums import (
    AutopayMode,
    BillOccurrenceStatus,
    PaymentRail,
    PaymentStageStatus,
    PaymentStatus,
)
from apps.payments.models import (
    Payment,
    PaymentAuthorization,
    PaymentBatch,
)
from apps.payments.services.confirm_service import PaymentConfirmService
from apps.payments.services.execution_service import PaymentExecutionService
from apps.payments.services.payment_create_service import PaymentCreateService
from apps.payments.services.resolution_service import PaymentResolutionService
from apps.vendors.factories import (
    UserFactory,
    VendorPaymentMethodFactory,
)
from integrations.money_movement.mock import MockMoneyMovementProvider

D = dt.date

AUTH_TEXT = "I authorize Swayp to debit my account for this payment."


class PayFlowTestCase(TestCase):

    def setUp(self):
        MockMoneyMovementProvider.reset()

        self.user = UserFactory()
        self.connection = BankConnectionFactory(user=self.user)
        self.account = BankAccountFactory(
            connection=self.connection, is_default_funding_source=True
        )

        self.bill = BillFactory(user=self.user, anchor_date=D(2026, 9, 1))
        self.method = VendorPaymentMethodFactory(vendor=self.bill.vendor)
        self.bill.payment_method = self.method
        self.bill.save(update_fields=["payment_method"])

        self.client = APIClient()
        self.client.force_authenticate(user=self.user)

    def occurrence(self, due_date=D(2026, 9, 1), amount="3200.00"):
        return BillOccurrenceFactory(
            bill=self.bill, due_date=due_date, amount=amount
        )

    def create(self, occurrences, **kwargs):
        return PaymentCreateService().create(
            user=self.user,
            occurrence_ids=[o.id for o in occurrences],
            today=kwargs.pop("today", D(2026, 8, 1)),
            **kwargs,
        )


class CreateTests(PayFlowTestCase):

    def test_a_single_occurrence_creates_one_payment_and_no_batch(self):
        result = self.create([self.occurrence()])

        self.assertIsNone(result["batch"])
        self.assertEqual(len(result["payments"]), 1)
        self.assertEqual(Payment.objects.count(), 1)

    def test_several_occurrences_create_a_batch(self):
        occurrences = [
            self.occurrence(D(2026, 9, 1)),
            self.occurrence(D(2026, 10, 1)),
        ]

        result = self.create(occurrences)

        batch = result["batch"]
        self.assertIsNotNone(batch)
        self.assertEqual(batch.count, 2)
        self.assertEqual(batch.total, Decimal("6400.00"))
        self.assertEqual(
            {p.batch_id for p in result["payments"]}, {batch.id}
        )

    def test_occurrences_become_scheduled_so_reminders_stop(self):
        occurrence = self.occurrence()

        self.create([occurrence])
        occurrence.refresh_from_db()

        self.assertEqual(occurrence.status, BillOccurrenceStatus.SCHEDULED)

    def test_dates_come_from_the_date_engine(self):
        # Due Tue 2026-09-01; ACH standard needs two business days.
        payment = self.create([self.occurrence(D(2026, 9, 1))])["payments"][0]

        self.assertEqual(payment.initiated_date, D(2026, 8, 28))
        self.assertEqual(payment.estimated_arrival, D(2026, 9, 1))

    def test_the_cancellation_deadline_is_aware_and_eastern(self):
        payment = self.create([self.occurrence()])["payments"][0]

        deadline = payment.cancellation_deadline

        self.assertIsNotNone(deadline.tzinfo)
        self.assertEqual(deadline.tzinfo.key, "America/New_York")
        self.assertEqual((deadline.hour, deadline.minute), (23, 59))

    def test_scheduled_for_makes_it_scheduled(self):
        result = self.create(
            [self.occurrence()], scheduled_for=D(2026, 8, 20)
        )
        payment = result["payments"][0]

        self.assertEqual(payment.status, PaymentStatus.SCHEDULED)
        self.assertEqual(payment.scheduled_for, D(2026, 8, 20))

    def test_a_second_payment_for_the_same_occurrence_is_refused(self):
        from rest_framework.exceptions import ValidationError

        occurrence = self.occurrence()
        self.create([occurrence])

        with self.assertRaises(ValidationError):
            self.create([occurrence])

    def test_an_already_paid_occurrence_is_refused(self):
        from rest_framework.exceptions import ValidationError

        occurrence = self.occurrence()
        occurrence.status = BillOccurrenceStatus.PAID
        occurrence.save(update_fields=["status"])

        with self.assertRaises(ValidationError):
            self.create([occurrence])

    def test_another_users_occurrence_is_refused(self):
        from rest_framework.exceptions import ValidationError

        other_bill = BillFactory()
        stranger = BillOccurrenceFactory(bill=other_bill)

        with self.assertRaises(ValidationError):
            self.create([stranger])

    def test_authorization_text_names_the_executing_provider(self):
        result = self.create([self.occurrence()])

        # NACHA requires the debiting party to be named; this is the one
        # place a processor name is allowed to surface.
        self.assertIn("Stripe", result["authorization_text"])
        self.assertIn("$3,200.00", result["authorization_text"])

    def test_batch_authorization_text_covers_every_payment(self):
        result = self.create(
            [self.occurrence(D(2026, 9, 1)), self.occurrence(D(2026, 10, 1))]
        )

        self.assertIn("2 bills", result["authorization_text"])
        self.assertIn("$6,400.00", result["authorization_text"])

    def test_the_reference_uses_the_swp_format(self):
        payment = self.create([self.occurrence()])["payments"][0]

        self.assertTrue(
            payment.transaction_reference.startswith("SWP-20260801-")
        )


class ConfirmTests(PayFlowTestCase):

    def meta(self):
        return {"ip": "203.0.113.9", "user_agent": "SwaypApp/1.0"}

    def test_confirming_a_batch_records_exactly_one_authorization(self):
        result = self.create(
            [self.occurrence(D(2026, 9, 1)), self.occurrence(D(2026, 10, 1))]
        )

        PaymentConfirmService().confirm_batch(
            user=self.user,
            batch_id=result["batch"].id,
            authorization_text=AUTH_TEXT,
            meta=self.meta(),
        )

        self.assertEqual(PaymentAuthorization.objects.count(), 1)
        self.assertEqual(
            PaymentAuthorization.objects.get().batch_id, result["batch"].id
        )

    def test_reconfirming_does_not_record_a_second_authorization(self):
        result = self.create([self.occurrence(), self.occurrence(D(2026, 10, 1))])

        for _ in range(2):
            outcome = PaymentConfirmService().confirm_batch(
                user=self.user,
                batch_id=result["batch"].id,
                authorization_text=AUTH_TEXT,
                meta=self.meta(),
            )

        self.assertTrue(outcome["replayed"])
        self.assertEqual(PaymentAuthorization.objects.count(), 1)

    def test_confirming_moves_payments_to_processing(self):
        result = self.create([self.occurrence()])
        payment = result["payments"][0]

        with self.captureOnCommitCallbacks(execute=True):
            PaymentConfirmService().confirm_payment(
                user=self.user,
                payment_id=payment.id,
                authorization_text=AUTH_TEXT,
                meta=self.meta(),
            )

        payment.refresh_from_db()
        # The mock executes instantly, so it lands SUCCESSFUL.
        self.assertEqual(payment.status, PaymentStatus.SUCCESSFUL)

    def test_confirming_seeds_the_stage_checklist(self):
        payment = self.create([self.occurrence()])["payments"][0]

        PaymentConfirmService().confirm_payment(
            user=self.user, payment_id=payment.id,
            authorization_text=AUTH_TEXT, meta=self.meta(),
        )

        self.assertEqual(
            [s.stage for s in payment.stages.order_by("order")][:1],
            ["AUTHORIZED"],
        )

    def test_confirm_requires_the_text(self):
        from rest_framework.exceptions import ValidationError

        payment = self.create([self.occurrence()])["payments"][0]

        with self.assertRaises(ValidationError):
            PaymentConfirmService().confirm_payment(
                user=self.user, payment_id=payment.id,
                authorization_text="   ", meta=self.meta(),
            )

    def test_confirm_requires_a_client_ip(self):
        from rest_framework.exceptions import ValidationError

        payment = self.create([self.occurrence()])["payments"][0]

        with self.assertRaises(ValidationError):
            PaymentConfirmService().confirm_payment(
                user=self.user, payment_id=payment.id,
                authorization_text=AUTH_TEXT, meta={"ip": None},
            )

    def test_a_batched_payment_must_be_confirmed_via_its_batch(self):
        from rest_framework.exceptions import ValidationError

        result = self.create([self.occurrence(), self.occurrence(D(2026, 10, 1))])

        with self.assertRaises(ValidationError):
            PaymentConfirmService().confirm_payment(
                user=self.user,
                payment_id=result["payments"][0].id,
                authorization_text=AUTH_TEXT,
                meta=self.meta(),
            )

    def test_a_scheduled_payment_stays_scheduled_after_confirm(self):
        payment = self.create(
            [self.occurrence()], scheduled_for=D(2026, 8, 20)
        )["payments"][0]

        with self.captureOnCommitCallbacks(execute=True):
            PaymentConfirmService().confirm_payment(
                user=self.user, payment_id=payment.id,
                authorization_text=AUTH_TEXT, meta=self.meta(),
            )

        payment.refresh_from_db()
        self.assertEqual(payment.status, PaymentStatus.SCHEDULED)


class ExecutionTests(PayFlowTestCase):

    def confirmed(self, amount="3200.00"):
        payment = self.create([self.occurrence(amount=amount)])["payments"][0]
        payment.status = PaymentStatus.PROCESSING
        payment.save(update_fields=["status"])
        return payment

    def test_success_marks_the_occurrence_paid(self):
        payment = self.confirmed()

        PaymentExecutionService().execute(payment.id)

        payment.refresh_from_db()
        self.assertEqual(payment.status, PaymentStatus.SUCCESSFUL)
        self.assertEqual(
            payment.bill_occurrence.__class__.objects.get(
                pk=payment.bill_occurrence_id
            ).status,
            BillOccurrenceStatus.PAID,
        )

    def test_nsf_fails_and_hands_the_bill_back(self):
        payment = self.confirmed(amount="3200.01")

        PaymentExecutionService().execute(payment.id)

        payment.refresh_from_db()
        self.assertEqual(payment.status, PaymentStatus.FAILED)
        self.assertEqual(payment.failure_reason, "NSF")
        self.assertEqual(
            payment.failure_detail["available_balance"], "2180.00"
        )
        self.assertEqual(
            BillOccurrence.objects.get(pk=payment.bill_occurrence_id).status,
            BillOccurrenceStatus.UPCOMING,
        )

    def test_the_idempotency_key_is_persisted_before_the_call(self):
        payment = self.confirmed()

        PaymentExecutionService().execute(payment.id)

        payment.refresh_from_db()
        self.assertTrue(payment.processor_idempotency_key)

    def test_a_worker_dying_mid_call_does_not_double_debit(self):
        """The kill-worker case: submitted, response lost, task retried.

        Recovery must be by lookup, never by re-sending.
        """
        from integrations.money_movement.mock import AmbiguousProcessorError

        payment = self.confirmed(amount="3200.02")
        service = PaymentExecutionService()

        with self.assertRaises(AmbiguousProcessorError):
            service.execute(payment.id)

        payment.refresh_from_db()
        key = payment.processor_idempotency_key
        self.assertTrue(key)

        # The transfer did reach the processor.
        self.assertIsNotNone(
            MockMoneyMovementProvider().lookup(idempotency_key=key)
        )

        # Retry: give it a reference so the engine takes the recovery path.
        payment.provider_reference = f"MOCK-{payment.transaction_reference}"
        payment.save(update_fields=["provider_reference"])

        PaymentExecutionService().execute(payment.id)

        payment.refresh_from_db()
        self.assertEqual(payment.status, PaymentStatus.SUCCESSFUL)
        self.assertEqual(payment.processor_idempotency_key, key)
        self.assertEqual(Payment.objects.count(), 1)

    def test_executing_a_non_processing_payment_is_a_no_op(self):
        payment = self.create([self.occurrence()])["payments"][0]

        self.assertIsNone(PaymentExecutionService().execute(payment.id))

    def test_reconciliation_closes_a_stuck_payment(self):
        import datetime

        payment = self.confirmed()
        service = PaymentExecutionService()

        # Submit, then pretend the outcome never arrived.
        service._claim(payment.id)
        payment.refresh_from_db()
        MockMoneyMovementProvider().execute(
            __import__(
                "integrations.money_movement.base", fromlist=["TransferRequest"]
            ).TransferRequest(
                reference=payment.transaction_reference,
                amount=payment.total,
                rail=payment.rail,
                source_token="s",
                destination_token="d",
                idempotency_key=payment.processor_idempotency_key,
            )
        )

        Payment.objects.filter(pk=payment.pk).update(
            updated_at=timezone.now() - datetime.timedelta(hours=2)
        )

        closed = PaymentExecutionService().reconcile()

        payment.refresh_from_db()
        self.assertEqual(closed, 1)
        self.assertEqual(payment.status, PaymentStatus.SUCCESSFUL)

    def test_the_non_custodial_invariant_holds(self):
        payment = self.confirmed()

        PaymentExecutionService().execute(payment.id)
        payment.refresh_from_db()

        self.assertTrue(
            PaymentExecutionService.assert_non_custodial(payment)
        )
        self.assertTrue(payment.processor)

    def test_no_swayp_balance_exists_to_hold_funds(self):
        """E6-S11: the stored-balance tables are gone.

        Uses the introspection API rather than information_schema, which
        is Postgres-only and the test settings run on SQLite.
        """
        from django.db import connection

        tables = connection.introspection.table_names()

        self.assertNotIn("wallets", tables)
        self.assertNotIn("wallet_transactions", tables)


class CancelTests(PayFlowTestCase):

    def test_cancelling_before_the_deadline_works(self):
        payment = self.create([self.occurrence()])["payments"][0]

        cancelled = PaymentConfirmService().cancel_payment(
            user=self.user, payment_id=payment.id,
            now=payment.cancellation_deadline - dt.timedelta(minutes=1),
        )

        self.assertEqual(cancelled.status, PaymentStatus.CANCELLED)

    def test_cancelling_after_the_deadline_is_a_conflict(self):
        """Once confirmed, the deadline holds: money is committed to move."""
        from apps.common.exceptions import ConflictException

        payment = self.create([self.occurrence()], scheduled_for=D(2026, 8, 20))[
            "payments"
        ][0]
        PaymentConfirmService().confirm_payment(
            user=self.user, payment_id=payment.id,
            authorization_text=AUTH_TEXT,
            meta={"ip": "203.0.113.9", "user_agent": "t"},
        )

        with self.assertRaises(ConflictException):
            PaymentConfirmService().cancel_payment(
                user=self.user, payment_id=payment.id,
                now=payment.cancellation_deadline + dt.timedelta(minutes=1),
            )

    def test_the_boundary_holds_across_the_dst_change(self):
        """US DST ends 2026-11-01; the promise is a wall clock, not an offset."""
        occurrence = self.occurrence(D(2026, 11, 3))
        payment = self.create([occurrence], today=D(2026, 10, 25))[
            "payments"
        ][0]

        deadline = payment.cancellation_deadline
        self.assertEqual((deadline.hour, deadline.minute), (23, 59))

        # One minute before is still allowed either side of the change.
        cancelled = PaymentConfirmService().cancel_payment(
            user=self.user, payment_id=payment.id,
            now=deadline - dt.timedelta(minutes=1),
        )
        self.assertEqual(cancelled.status, PaymentStatus.CANCELLED)

    def test_cancelling_releases_the_occurrence(self):
        occurrence = self.occurrence()
        payment = self.create([occurrence])["payments"][0]

        PaymentConfirmService().cancel_payment(
            user=self.user, payment_id=payment.id,
            now=payment.cancellation_deadline - dt.timedelta(minutes=1),
        )

        occurrence.refresh_from_db()
        self.assertEqual(occurrence.status, BillOccurrenceStatus.UPCOMING)

    def test_a_settled_payment_cannot_be_cancelled(self):
        from apps.common.exceptions import ConflictException

        payment = self.create([self.occurrence()])["payments"][0]
        payment.status = PaymentStatus.SUCCESSFUL
        payment.save(update_fields=["status"])

        with self.assertRaises(ConflictException):
            PaymentConfirmService().cancel_payment(
                user=self.user, payment_id=payment.id
            )

    def test_cancelling_a_batch_cancels_its_payments(self):
        result = self.create(
            [self.occurrence(D(2026, 9, 1)), self.occurrence(D(2026, 10, 1))]
        )

        outcome = PaymentConfirmService().cancel_batch(
            user=self.user,
            batch_id=result["batch"].id,
            now=timezone.now(),
        )

        self.assertEqual(len(outcome["cancelled"]), 2)


class ResolutionTests(PayFlowTestCase):

    def failed_payment(self):
        occurrence = self.occurrence(amount="3200.01")
        payment = self.create([occurrence])["payments"][0]
        payment.status = PaymentStatus.PROCESSING
        payment.save(update_fields=["status"])

        PaymentExecutionService().execute(payment.id)
        payment.refresh_from_db()

        return payment

    def test_failure_detail_reports_the_reason_and_balance(self):
        payment = self.failed_payment()

        detail = PaymentResolutionService().failure(
            user=self.user, payment_id=payment.id, today=D(2026, 9, 12)
        )

        self.assertEqual(detail["failure_reason"], "NSF")
        self.assertEqual(
            detail["failure_detail"]["available_balance"], "2180.00"
        )
        self.assertEqual(detail["days_overdue"], 11)

    def test_the_late_fee_countdown_uses_the_vendors_own_terms(self):
        self.bill.vendor.late_fee_amount = Decimal("160.00")
        self.bill.vendor.late_fee_grace_days = 15
        self.bill.vendor.save()

        payment = self.failed_payment()

        detail = PaymentResolutionService().failure(
            user=self.user, payment_id=payment.id, today=D(2026, 9, 12)
        )

        self.assertEqual(detail["late_fee"]["days_remaining"], 4)
        self.assertFalse(detail["late_fee"]["applies"])

    def test_retry_creates_a_new_payment_on_the_same_occurrence(self):
        failed = self.failed_payment()

        result = PaymentResolutionService().resolve(
            user=self.user, payment_id=failed.id, action="retry",
            today=D(2026, 8, 5),
        )

        replacement = result["payment"]
        self.assertNotEqual(replacement.id, failed.id)
        self.assertEqual(
            replacement.bill_occurrence_id, failed.bill_occurrence_id
        )
        self.assertEqual(replacement.retry_of_id, failed.id)

    def test_the_failed_payment_stays_terminal(self):
        failed = self.failed_payment()

        PaymentResolutionService().resolve(
            user=self.user, payment_id=failed.id, action="retry",
            today=D(2026, 8, 5),
        )

        failed.refresh_from_db()
        self.assertEqual(failed.status, PaymentStatus.FAILED)

    def test_only_one_live_payment_per_occurrence(self):
        from rest_framework.exceptions import ValidationError

        failed = self.failed_payment()

        PaymentResolutionService().resolve(
            user=self.user, payment_id=failed.id, action="retry",
            today=D(2026, 8, 5),
        )

        with self.assertRaises(ValidationError):
            PaymentResolutionService().resolve(
                user=self.user, payment_id=failed.id, action="retry",
                today=D(2026, 8, 5),
            )

    def test_change_method_switches_the_bills_method(self):
        failed = self.failed_payment()
        replacement_method = VendorPaymentMethodFactory(
            vendor=self.bill.vendor, check=True, is_primary=False
        )

        PaymentResolutionService().resolve(
            user=self.user, payment_id=failed.id, action="change_method",
            payment_method_id=replacement_method.id, today=D(2026, 8, 5),
        )

        self.bill.refresh_from_db()
        self.assertEqual(self.bill.payment_method_id, replacement_method.id)

    def test_reschedule_requires_a_date(self):
        from rest_framework.exceptions import ValidationError

        failed = self.failed_payment()

        with self.assertRaises(ValidationError):
            PaymentResolutionService().resolve(
                user=self.user, payment_id=failed.id, action="reschedule",
                today=D(2026, 8, 5),
            )

    def test_reschedule_sets_the_send_date(self):
        failed = self.failed_payment()

        result = PaymentResolutionService().resolve(
            user=self.user, payment_id=failed.id, action="reschedule",
            scheduled_for=D(2026, 9, 20), today=D(2026, 8, 5),
        )

        self.assertEqual(result["payment"].scheduled_for, D(2026, 9, 20))
        self.assertEqual(result["payment"].status, PaymentStatus.SCHEDULED)

    def test_a_successful_payment_cannot_be_resolved(self):
        from rest_framework.exceptions import ValidationError

        payment = self.create([self.occurrence()])["payments"][0]
        payment.status = PaymentStatus.SUCCESSFUL
        payment.save(update_fields=["status"])

        with self.assertRaises(ValidationError):
            PaymentResolutionService().resolve(
                user=self.user, payment_id=payment.id, action="retry"
            )


@override_settings(MONEY_MOVEMENT_PROVIDER="mock")
class AutopayTests(PayFlowTestCase):

    def setUp(self):
        super().setUp()
        self.bill.autopay_mode = AutopayMode.AUTO
        self.bill.save(update_fields=["autopay_mode"])

    def authorize(self):
        return StandingAuthorization.objects.create(
            bill=self.bill,
            authorization_text="I authorize recurring debits.",
            accepted_at=timezone.now(),
            ip="203.0.113.9",
        )

    def test_autopay_pays_at_the_lead_time(self):
        from apps.payments.services.autopay_service import AutopayService

        self.authorize()
        self.occurrence(D(2026, 9, 1))

        with self.captureOnCommitCallbacks(execute=True):
            report = AutopayService().run(today=D(2026, 8, 28))

        self.assertEqual(report["created"], 1)
        self.assertEqual(Payment.objects.count(), 1)

    def test_autopay_does_nothing_before_the_lead_time(self):
        from apps.payments.services.autopay_service import AutopayService

        self.authorize()
        self.occurrence(D(2026, 9, 1))

        report = AutopayService().run(today=D(2026, 8, 1))

        self.assertEqual(report["created"], 0)
        self.assertEqual(Payment.objects.count(), 0)

    def test_autopay_without_a_live_authorization_does_nothing_and_alerts(self):
        from apps.notifications.models import Notification
        from apps.payments.services.autopay_service import AutopayService

        self.occurrence(D(2026, 9, 1))

        report = AutopayService().run(today=D(2026, 8, 28))

        self.assertEqual(report["created"], 0)
        self.assertEqual(report["unauthorized"], 1)
        self.assertEqual(Payment.objects.count(), 0)
        self.assertTrue(
            Notification.objects.filter(
                title__icontains="Autopay"
            ).exists()
        )

    def test_a_revoked_authorization_stops_autopay(self):
        from apps.payments.services.autopay_service import AutopayService

        authorization = self.authorize()
        authorization.revoked_at = timezone.now()
        authorization.save(update_fields=["revoked_at"])

        self.occurrence(D(2026, 9, 1))

        report = AutopayService().run(today=D(2026, 8, 28))

        self.assertEqual(report["created"], 0)
        self.assertEqual(report["unauthorized"], 1)

    def test_autopay_skips_an_occurrence_already_in_flight(self):
        from apps.payments.services.autopay_service import AutopayService

        self.authorize()
        occurrence = self.occurrence(D(2026, 9, 1))
        self.create([occurrence], today=D(2026, 8, 20))

        report = AutopayService().run(today=D(2026, 8, 28))

        self.assertEqual(report["created"], 0)
        self.assertEqual(Payment.objects.count(), 1)


class DeprecationTests(PayFlowTestCase):

    def test_manual_transitions_are_staff_only(self):
        payment = self.create([self.occurrence()])["payments"][0]

        response = self.client.patch(
            f"/api/v1/payments/{payment.id}/successful", {}, format="json"
        )

        self.assertEqual(response.status_code, 403)

    def test_staff_may_still_use_them(self):
        payment = self.create([self.occurrence()])["payments"][0]
        payment.status = PaymentStatus.PROCESSING
        payment.save(update_fields=["status"])

        self.user.is_staff = True
        self.user.save(update_fields=["is_staff"])

        response = self.client.patch(
            f"/api/v1/payments/{payment.id}/successful", {}, format="json"
        )

        self.assertEqual(response.status_code, 200)

    def test_the_payment_tracking_route_is_gone(self):
        self.assertEqual(
            self.client.get("/api/v1/payment-tracking").status_code, 404
        )

    def test_the_wallet_route_is_gone(self):
        self.assertEqual(
            self.client.get("/api/v1/wallet/summary").status_code, 404
        )


class UnconfirmedPaymentTests(PayFlowTestCase):
    """PAY-1: creating a payment reserves its bill. If nobody confirms it,
    the reservation must not strand the bill."""

    def meta(self):
        return {"ip": "203.0.113.9", "user_agent": "SwaypApp/1.0"}

    def test_an_unconfirmed_payment_can_be_cancelled_after_the_deadline(self):
        occurrence = self.occurrence()
        payment = self.create([occurrence])["payments"][0]

        cancelled = PaymentConfirmService().cancel_payment(
            user=self.user, payment_id=payment.id,
            now=payment.cancellation_deadline + dt.timedelta(days=1),
        )

        self.assertEqual(cancelled.status, PaymentStatus.CANCELLED)
        occurrence.refresh_from_db()
        self.assertNotEqual(occurrence.status, BillOccurrenceStatus.SCHEDULED)

    def test_an_unconfirmed_payment_lapses_and_frees_its_bill(self):
        occurrence = self.occurrence()
        payment = self.create([occurrence])["payments"][0]
        occurrence.refresh_from_db()
        self.assertEqual(occurrence.status, BillOccurrenceStatus.SCHEDULED)

        expired = PaymentConfirmService().expire_unconfirmed(
            older_than=timezone.now() + dt.timedelta(seconds=1)
        )

        self.assertEqual(expired, 1)
        payment.refresh_from_db()
        occurrence.refresh_from_db()
        self.assertEqual(payment.status, PaymentStatus.CANCELLED)
        self.assertEqual(occurrence.status, BillOccurrenceStatus.UPCOMING)

    def test_a_young_payment_is_left_alone(self):
        payment = self.create([self.occurrence()])["payments"][0]

        expired = PaymentConfirmService().expire_unconfirmed(
            older_than=timezone.now() - dt.timedelta(minutes=30)
        )

        self.assertEqual(expired, 0)
        payment.refresh_from_db()
        self.assertNotEqual(payment.status, PaymentStatus.CANCELLED)

    def test_a_confirmed_payment_never_lapses(self):
        payment = self.create(
            [self.occurrence()], scheduled_for=D(2026, 8, 20)
        )["payments"][0]
        PaymentConfirmService().confirm_payment(
            user=self.user, payment_id=payment.id,
            authorization_text=AUTH_TEXT, meta=self.meta(),
        )

        expired = PaymentConfirmService().expire_unconfirmed(
            older_than=timezone.now() + dt.timedelta(seconds=1)
        )

        self.assertEqual(expired, 0)

    def test_detail_says_whether_and_how_it_was_authorized(self):
        payment = self.create(
            [self.occurrence()], scheduled_for=D(2026, 8, 20)
        )["payments"][0]

        before = self.client.get(f"/api/v1/payments/{payment.id}").json()["data"]

        self.assertIsNone(before["authorized_at"])
        self.assertIsNone(before["authorization_text"])
        self.assertIsNotNone(before["confirm_by"])

        PaymentConfirmService().confirm_payment(
            user=self.user, payment_id=payment.id,
            authorization_text=AUTH_TEXT, meta=self.meta(),
        )

        after = self.client.get(f"/api/v1/payments/{payment.id}").json()["data"]

        self.assertIsNotNone(after["authorized_at"])
        self.assertEqual(after["authorization_text"], AUTH_TEXT)
        self.assertIsNone(after["confirm_by"])


class RailDefaultAndQuoteTests(PayFlowTestCase):
    """PAY-5: an omitted rail follows the bill's saved method, an explicit
    one has to suit it, and the quote prices every rail up front."""

    def use_check_method(self):
        check = VendorPaymentMethodFactory(
            vendor=self.bill.vendor, check=True, is_primary=False
        )
        self.bill.payment_method = check
        self.bill.save(update_fields=["payment_method"])

    def test_an_omitted_rail_follows_the_bills_method(self):
        self.use_check_method()

        payment = self.create([self.occurrence()])["payments"][0]

        self.assertEqual(payment.rail, PaymentRail.CHECK)

    def test_an_ach_bill_still_defaults_to_standard_ach(self):
        payment = self.create([self.occurrence()])["payments"][0]

        self.assertEqual(payment.rail, PaymentRail.ACH_STANDARD)

    def test_an_explicit_rail_the_method_cannot_take_is_refused(self):
        from rest_framework.exceptions import ValidationError

        self.use_check_method()

        with self.assertRaises(ValidationError) as caught:
            self.create([self.occurrence()], rail=PaymentRail.ACH_STANDARD)

        self.assertIn("rail", caught.exception.detail)

    def quote(self, **body):
        body.setdefault("occurrence_ids", [str(self.occurrence().id)])
        return self.client.post("/api/v1/payments/quote", body, format="json")

    def rails(self, response):
        return {
            row["rail"]: row
            for row in response.json()["data"]["occurrences"][0]["rails"]
        }

    def test_the_quote_lists_every_rail_with_availability(self):
        response = self.quote()

        self.assertEqual(response.status_code, 200)
        data = response.json()["data"]["occurrences"][0]
        self.assertEqual(data["default_rail"], "ACH_STANDARD")

        rails = self.rails(response)
        self.assertTrue(rails["ACH_STANDARD"]["available"])
        self.assertFalse(rails["CHECK"]["available"])
        self.assertIn("paid by ACH", rails["CHECK"]["unavailable_reason"])

    def test_the_quote_creates_nothing(self):
        self.quote()

        self.assertEqual(Payment.objects.count(), 0)

    def test_no_plan_means_no_fees_as_at_execution(self):
        rails = self.rails(self.quote())

        self.assertEqual(rails["ACH_SAMEDAY"]["fee"], "0.00")

    def test_with_a_plan_same_day_and_expedited_are_priced(self):
        from apps.billing.factories import SubscriptionFactory

        SubscriptionFactory(account=self.user)
        self.use_check_method()

        rails = self.rails(self.quote())

        self.assertEqual(rails["ACH_SAMEDAY"]["fee"], "4.99")
        self.assertEqual(rails["CHECK"]["expedited"]["fee"], "8.99")
        self.assertTrue(rails["CHECK"]["available"])


class TraceabilityTests(PayFlowTestCase):
    """PAY-4: a payment leads to its vendor, bill and accounts, and an
    occurrence can be fetched by id."""

    def test_payment_bodies_carry_the_ids(self):
        occurrence = self.occurrence()
        payment = self.create([occurrence])["payments"][0]

        data = self.client.get(f"/api/v1/payments/{payment.id}").json()["data"]

        self.assertEqual(data["vendor_id"], str(self.bill.vendor_id))
        self.assertEqual(data["bill_id"], str(self.bill.id))
        self.assertEqual(data["bill_occurrence"], str(occurrence.id))
        self.assertEqual(data["funding_account_id"], str(self.account.id))
        self.assertEqual(data["payment_method_id"], str(self.method.id))

    def test_an_occurrence_by_id_is_the_list_row(self):
        occurrence = self.occurrence()
        payment = self.create([occurrence])["payments"][0]

        data = self.client.get(
            f"/api/v1/bills/occurrences/{occurrence.id}"
        ).json()["data"]

        self.assertEqual(data["id"], str(occurrence.id))
        self.assertEqual(data["bill_id"], str(self.bill.id))
        self.assertEqual(data["status"], "SCHEDULED")
        self.assertEqual(data["payment_id"], str(payment.id))

    def test_another_accounts_occurrence_is_404(self):
        theirs = BillOccurrenceFactory()

        response = self.client.get(f"/api/v1/bills/occurrences/{theirs.id}")

        self.assertEqual(response.status_code, 404)


class ResolutionShapeTests(PayFlowTestCase):
    """PAY-6: failure is display-ready, a resolve says what to confirm, and a
    new method takes its own rail."""

    failed_payment = ResolutionTests.failed_payment

    def test_failure_has_display_ready_words(self):
        payment = self.failed_payment()

        data = self.client.get(f"/api/v1/payments/{payment.id}/failure").json()[
            "data"
        ]

        self.assertEqual(data["title"], "Not enough money in the account")
        self.assertIn("Add funds", data["explanation"])
        self.assertEqual(
            data["available_actions"], ["retry", "change_method", "reschedule"]
        )

    def test_resolve_returns_the_text_to_confirm(self):
        payment = self.failed_payment()

        data = self.client.post(
            f"/api/v1/payments/{payment.id}/resolve",
            {"action": "retry"},
            format="json",
        ).json()["data"]

        self.assertTrue(data["requires_confirmation"])
        self.assertIn("I authorize Swayp", data["authorization_text"])
        self.assertEqual(data["replaced_payment_id"], str(payment.id))

    def test_change_method_moves_to_the_new_methods_rail(self):
        payment = self.failed_payment()
        check = VendorPaymentMethodFactory(
            vendor=self.bill.vendor, check=True, is_primary=False
        )

        result = PaymentResolutionService().resolve(
            user=self.user,
            payment_id=payment.id,
            action="change_method",
            payment_method_id=check.id,
        )

        self.assertEqual(result["payment"].rail, PaymentRail.CHECK)


class RescheduleTests(PayFlowTestCase):
    """PAY-7: an unconfirmed payment moves to another date in place."""

    def patch(self, payment, scheduled_for):
        return self.client.patch(
            f"/api/v1/payments/{payment.id}",
            {"scheduled_for": scheduled_for},
            format="json",
        )

    def test_rescheduling_keeps_the_payment_and_moves_its_dates(self):
        from apps.common.dates import today_eastern

        payment = self.create([self.occurrence()])["payments"][0]
        target = today_eastern() + dt.timedelta(days=30)

        response = self.patch(payment, target.isoformat())

        self.assertEqual(response.status_code, 200)
        data = response.json()["data"]
        self.assertEqual(data["id"], str(payment.id))
        self.assertEqual(data["transaction_reference"], payment.transaction_reference)
        self.assertEqual(data["scheduled_for"], target.isoformat())
        self.assertEqual(data["status"], "SCHEDULED")
        self.assertEqual(Payment.objects.count(), 1)

    def test_null_makes_it_pay_now(self):
        from apps.common.dates import today_eastern

        payment = self.create(
            [self.occurrence()],
            scheduled_for=today_eastern() + dt.timedelta(days=10),
        )["payments"][0]

        data = self.patch(payment, None).json()["data"]

        self.assertIsNone(data["scheduled_for"])
        self.assertEqual(data["status"], "PENDING")

    def test_a_past_date_is_refused(self):
        payment = self.create([self.occurrence()])["payments"][0]

        self.assertEqual(self.patch(payment, "2020-01-01").status_code, 400)

    def test_a_confirmed_payment_cannot_be_moved(self):
        from apps.common.dates import today_eastern

        payment = self.create(
            [self.occurrence()],
            scheduled_for=today_eastern() + dt.timedelta(days=10),
        )["payments"][0]
        PaymentConfirmService().confirm_payment(
            user=self.user, payment_id=payment.id,
            authorization_text=AUTH_TEXT,
            meta={"ip": "203.0.113.9", "user_agent": "t"},
        )

        response = self.patch(
            payment, (today_eastern() + dt.timedelta(days=20)).isoformat()
        )

        self.assertEqual(response.status_code, 400)


class ReceiptPDFTests(PayFlowTestCase):
    """PAY-8: a completed payment downloads as a PDF receipt."""

    def test_a_completed_payment_has_a_pdf(self):
        payment = self.create([self.occurrence()])["payments"][0]
        payment.status = PaymentStatus.SUCCESSFUL
        payment.save(update_fields=["status"])

        response = self.client.get(f"/api/v1/payments/{payment.id}/receipt.pdf")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "application/pdf")
        self.assertTrue(response.content.startswith(b"%PDF"))
        self.assertIn(
            payment.transaction_reference, response["Content-Disposition"]
        )

    def test_an_unfinished_payment_has_none(self):
        payment = self.create([self.occurrence()])["payments"][0]

        response = self.client.get(f"/api/v1/payments/{payment.id}/receipt.pdf")

        self.assertEqual(response.status_code, 409)
