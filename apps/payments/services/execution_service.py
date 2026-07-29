"""Payment execution and reconciliation (E6-S7).

Non-custodial invariant (BRD §4): this module orchestrates only. It never
credits or debits a Swayp-held balance — money moves at the licensed provider,
and every payment records which one and its reference.

The ambiguity rule matters more than the happy path. If a worker dies after
calling the processor but before recording the result, retrying blindly could
debit twice. So the idempotency key is persisted **before** the call, and a
retry queries the processor by that key rather than re-sending.
"""

import logging
import uuid

from django.db import transaction
from django.utils import timezone

from apps.common.enums import (
    NotificationType,
    PaymentProcessor,
    PaymentStageStatus,
    PaymentStatus,
)
from apps.notifications.services import notify
from apps.payments.models import Payment, PaymentStageName
from apps.payments.services.notification_context import payment_context
from apps.payments.services.stage_service import StageService
from integrations.factory import get_money_movement_provider
from integrations.money_movement.base import TransferRequest

logger = logging.getLogger(__name__)

#: Statuses a reconciliation sweep considers stuck.
SWEEPABLE = (PaymentStatus.PROCESSING,)

#: How long a payment may sit PROCESSING before the sweep looks at it.
STUCK_AFTER_MINUTES = 30


class PaymentExecutionService:

    def __init__(self):
        self.stages = StageService()
        self.provider = get_money_movement_provider()

    # --- execution --------------------------------------------------------

    def execute(self, payment_id):
        """Run one payment through the processor.

        Deliberately not wrapped in a single transaction: the idempotency key
        must be committed before the external call, or a crash would lose the
        only handle we have on an in-flight transfer.
        """
        payment = self._claim(payment_id)

        if payment is None:
            return None

        result = self._call_processor(payment)

        return self._apply(payment, result)

    @transaction.atomic
    def _claim(self, payment_id):
        """Lock the payment, stamp its idempotency key, and commit.

        Returns None when the payment is not executable, so a duplicate task
        delivery is a no-op rather than a second debit.
        """
        payment = (
            Payment.objects.select_for_update()
            .filter(id=payment_id)
            .first()
        )

        if payment is None:
            logger.warning("execute: payment %s no longer exists", payment_id)
            return None

        if payment.status != PaymentStatus.PROCESSING:
            logger.info(
                "execute: payment %s is %s, nothing to do",
                payment.transaction_reference,
                payment.status,
            )
            return None

        if not payment.processor_idempotency_key:
            payment.processor_idempotency_key = uuid.uuid4().hex
            payment.save(
                update_fields=["processor_idempotency_key", "updated_at"]
            )

        self.stages.seed(payment)
        self.stages.mark(
            payment, PaymentStageName.DEBITING, PaymentStageStatus.RUNNING
        )

        # Billed at send, not at success: a check that goes out has been
        # printed and mailed whatever the bank does next, and same-day is
        # charged for the slot it occupies (E9-S3).
        self._charge_fee(payment)

        return payment

    def _charge_fee(self, payment):
        """Apply any per-transaction fee this payment attracts (E9-S3).

        Never allowed to break execution: a billing failure must not stop
        money that the customer already authorised. The fee ledger is
        reconcilable after the fact; a stranded payment is not.
        """
        from apps.billing.services.fee_service import FeeService
        from apps.billing.services.subscription_service import (
            SubscriptionService,
        )

        try:
            subscription = SubscriptionService().current(payment.user)

            if subscription is None:
                return None

            return FeeService().charge_for_payment(
                subscription=subscription,
                payment=payment,
                expedited=bool(
                    (payment.failure_detail or {}).get("expedited")
                ),
            )
        except Exception:
            logger.exception(
                "fee charging failed for %s; execution continues",
                payment.transaction_reference,
            )

            return None

    def _call_processor(self, payment):
        """Ask the processor to move the money, or recover a prior attempt.

        A payment that already carries a provider_reference was submitted on a
        previous attempt; querying by key is the only safe way to learn how it
        ended.
        """
        if payment.provider_reference:
            recovered = self._lookup(payment)

            if recovered is not None:
                return recovered

        transfer = TransferRequest(
            reference=payment.transaction_reference,
            amount=payment.total,
            rail=payment.rail,
            source_token=self._source_token(payment),
            destination_token=self._destination_token(payment),
            idempotency_key=payment.processor_idempotency_key,
        )

        return self.provider.execute(transfer)

    def _lookup(self, payment):
        """Query the processor by idempotency key, if it supports it."""
        lookup = getattr(self.provider, "lookup", None)

        if not callable(lookup):
            return None

        return lookup(idempotency_key=payment.processor_idempotency_key)

    @transaction.atomic
    def _apply(self, payment, result):
        payment = (
            Payment.objects.select_for_update().get(pk=payment.pk)
        )

        payment.provider_reference = result.provider_reference

        for event in result.stages:
            self.stages.mark(payment, event.stage, event.status, event.detail)

        if result.status == PaymentStatus.SUCCESSFUL:
            self._succeed(payment, result)
        else:
            self._fail(payment, result)

        return payment

    def _succeed(self, payment, result):
        from apps.bills.models.bill_occurrence import BillOccurrence
        from apps.common.enums import BillOccurrenceStatus

        payment.status = PaymentStatus.SUCCESSFUL

        if result.estimated_arrival:
            payment.estimated_arrival = result.estimated_arrival

        payment.save(
            update_fields=[
                "status",
                "provider_reference",
                "estimated_arrival",
                "updated_at",
            ]
        )

        # BRD §4 invariant, enforced at runtime rather than assumed: a settled
        # payment must name the licensed provider that moved the money.
        self.assert_non_custodial(payment)

        self.stages.mark(
            payment, PaymentStageName.COMPLETED, PaymentStageStatus.DONE
        )

        if payment.bill_occurrence_id:
            BillOccurrence.objects.filter(
                pk=payment.bill_occurrence_id
            ).update(
                status=BillOccurrenceStatus.PAID,
                paid_at=timezone.now(),
                payment_reference=payment.transaction_reference,
            )

        # Stays on the generic PAYMENT type: SUCCESSFUL at the processor is
        # not arrival — a check is five business days from sent to arrived,
        # which is why estimated_arrival exists. PAYMENT_ARRIVED belongs to
        # the webhook consumer.
        notify(
            payment.user,
            NotificationType.PAYMENT,
            payment_context(payment),
            title="Payment successful",
            message=f"{payment.transaction_reference} completed successfully.",
        )

    def _settle_guarantee(self, payment):
        """Refund a guaranteed fee when the arrival date was missed."""
        from apps.billing.services.fee_service import FeeService

        try:
            return FeeService().settle_guarantee(
                payment=payment,
                actual_arrival=payment.estimated_arrival,
            )
        except Exception:
            logger.exception(
                "guarantee settlement failed for %s",
                payment.transaction_reference,
            )

            return []

    def _fail(self, payment, result):
        from apps.bills.models.bill_occurrence import BillOccurrence
        from apps.common.enums import BillOccurrenceStatus

        detail = getattr(result, "failure_detail", {}) or {}
        reason = getattr(result, "failure_reason", "") or "PROCESSOR_DECLINED"

        payment.status = PaymentStatus.FAILED
        payment.failure_reason = reason
        payment.failure_detail = detail
        payment.save(
            update_fields=[
                "status",
                "provider_reference",
                "failure_reason",
                "failure_detail",
                "updated_at",
            ]
        )

        self.stages.fail(payment, detail=reason)

        # Hand the occurrence back so the bill reads as owed again.
        if payment.bill_occurrence_id:
            BillOccurrence.objects.filter(
                pk=payment.bill_occurrence_id,
                status=BillOccurrenceStatus.SCHEDULED,
            ).update(status=BillOccurrenceStatus.UPCOMING)

        notify(
            payment.user,
            NotificationType.PAYMENT_FAILED,
            {**payment_context(payment), "reason": reason},
        )

    def _source_token(self, payment):
        account = payment.funding_account

        if account is None:
            return ""

        return account.processor_refs.get("funding_source_id") or str(
            account.id
        )

    def _destination_token(self, payment):
        method = None

        if payment.bill_occurrence_id and payment.bill_occurrence.bill:
            method = payment.bill_occurrence.bill.payment_method

        if method is None:
            return ""

        return method.provider_token or method.network_payee_ref or ""

    # --- reconciliation ---------------------------------------------------

    def stuck_payments(self, now=None):
        """PROCESSING payments the processor never reported back on."""
        import datetime as dt

        now = now or timezone.now()
        cutoff = now - dt.timedelta(minutes=STUCK_AFTER_MINUTES)

        return Payment.objects.filter(
            status__in=SWEEPABLE, updated_at__lt=cutoff
        )

    def reconcile(self, now=None):
        """Close out payments the processor never reported back on.

        Queries by idempotency key rather than assuming an outcome — a stuck
        payment may well have succeeded.
        """
        closed = 0

        for payment in self.stuck_payments(now).iterator():
            recovered = self._lookup(payment)

            if recovered is None:
                logger.warning(
                    "reconcile: no processor record for %s",
                    payment.transaction_reference,
                )
                continue

            self._apply(payment, recovered)
            closed += 1

        return closed

    # --- invariant --------------------------------------------------------

    @staticmethod
    def assert_non_custodial(payment):
        """Every executed payment names the licensed provider that moved it.

        BRD §4 is an architectural invariant, so it is asserted rather than
        assumed.
        """
        if payment.status != PaymentStatus.SUCCESSFUL:
            return True

        if not payment.processor:
            raise AssertionError(
                f"{payment.transaction_reference} has no executing processor."
            )

        if payment.processor != PaymentProcessor.MOCK and (
            not payment.provider_reference
        ):
            raise AssertionError(
                f"{payment.transaction_reference} has no provider reference; "
                "a completed transfer must be traceable to the provider."
            )

        return True
