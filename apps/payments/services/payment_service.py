"""Legacy payment status transitions and history (E6-S10 / E6-S11).

What this used to do: debit ``Wallet.balance`` on create and credit it back on
failure. That is a custodial flow — funds resting in a Swayp-controlled
balance — and BRD §4 forbids it. The wallet is gone; money now moves at the
licensed provider and never through Swayp.

What remains: payment history, and the manual status transitions that predate
the execution engine. Those are now **staff-only** (E6-S10) — status is driven
by the processor and its webhooks, not by a client call.
"""

from django.db import transaction
from django.utils import timezone

from apps.common.enums import NotificationType, PaymentStatus
from apps.notifications.services import notify
from apps.payments.repositories import PaymentRepository
from apps.payments.selectors.payment_selector import PaymentSelector
from apps.payments.services.notification_context import payment_context
from apps.payments.services.payment_state_service import PaymentStateService
from apps.payments.services.stage_service import StageService


class PaymentService:

    def __init__(self):
        self.selector = PaymentSelector()
        self.repository = PaymentRepository()
        self.stages = StageService()

    def payment_history(
        self,
        *,
        user,
        page,
        page_size,
        status=None,
        provider_id=None,
        category_id=None,
        from_date=None,
        to_date=None,
        search=None,
    ):
        return self.selector.list_payments(
            user=user,
            page=page,
            page_size=page_size,
            status=status,
            provider_id=provider_id,
            category_id=category_id,
            from_date=from_date,
            to_date=to_date,
            search=search,
        )

    # --- manual transitions, staff-only (E6-S10) --------------------------

    @transaction.atomic
    def mark_processing(self, *, user, payment_id):
        payment = self.repository.get_for_update(
            payment_id=payment_id, user=user
        )

        PaymentStateService.to_processing(payment)

        PaymentRepository.update_status(
            payment=payment, status=PaymentStatus.PROCESSING
        )

        # No typed member covers "processing", and this is a staff-only
        # manual transition, so it keeps the generic type and its own copy.
        notify(
            payment.user,
            NotificationType.PAYMENT,
            payment_context(payment),
            title="Payment processing",
            message=(
                f"Payment {payment.transaction_reference} is being processed."
            ),
        )

        return payment

    @transaction.atomic
    def mark_successful(self, *, user, payment_id):
        from apps.bills.models.bill_occurrence import BillOccurrence
        from apps.common.enums import BillOccurrenceStatus, PaymentStageStatus
        from apps.payments.models import PaymentStageName

        payment = self.repository.get_for_update(
            payment_id=payment_id, user=user
        )

        PaymentStateService.to_success(payment)

        PaymentRepository.update_status(
            payment=payment, status=PaymentStatus.SUCCESSFUL
        )

        self.stages.seed(payment)
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

        notify(
            payment.user,
            NotificationType.PAYMENT,
            payment_context(payment),
            title="Payment successful",
            message=(
                f"Payment {payment.transaction_reference} completed "
                "successfully."
            ),
        )

        return payment

    @transaction.atomic
    def mark_failed(self, *, user, payment_id):
        from apps.bills.models.bill_occurrence import BillOccurrence
        from apps.common.enums import BillOccurrenceStatus

        payment = self.repository.get_for_update(
            payment_id=payment_id, user=user
        )

        PaymentStateService.to_failed(payment)

        PaymentRepository.update_status(
            payment=payment, status=PaymentStatus.FAILED
        )

        self.stages.fail(payment, detail="Marked failed")

        # Nothing to refund: no money ever sat in a Swayp balance. The bill
        # simply becomes owed again.
        if payment.bill_occurrence_id:
            BillOccurrence.objects.filter(
                pk=payment.bill_occurrence_id,
                status=BillOccurrenceStatus.SCHEDULED,
            ).update(status=BillOccurrenceStatus.UPCOMING)

        # Same detail the stage already records, so the notification and the
        # stage trail cannot tell different stories.
        notify(
            payment.user,
            NotificationType.PAYMENT_FAILED,
            {**payment_context(payment), "reason": "Marked failed"},
        )

        return payment
