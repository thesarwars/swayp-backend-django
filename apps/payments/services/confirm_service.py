"""Confirmation and consent (E6-S3), plus cancellation (E6-S5).

Confirming records exactly one PaymentAuthorization — for the batch when there
is one, otherwise for the single payment — and hands the work to the execution
engine. Re-confirming does not write a second authorization.
"""

from django.db import transaction
from django.utils import timezone
from rest_framework.exceptions import ValidationError

from apps.common.enums import PaymentStageStatus, PaymentStatus
from apps.common.exceptions import ConflictException
from apps.payments.models import (
    Payment,
    PaymentAuthorization,
    PaymentBatch,
    PaymentStageName,
)
from apps.payments.services.stage_service import StageService

CONFIRMABLE = (PaymentStatus.SCHEDULED, PaymentStatus.PENDING)

CANCELLABLE = (
    PaymentStatus.SCHEDULED,
    PaymentStatus.PENDING,
    PaymentStatus.PROCESSING,
)


def is_confirmed(payment):
    """Has the user (or a standing authorization) approved this payment?

    The AUTHORIZED stage is marked DONE at confirm, and by autopay from the
    bill's standing authorization. An unconfirmed payment has no stages at
    all: they are seeded at confirm.
    """
    return payment.stages.filter(
        stage=PaymentStageName.AUTHORIZED,
        status=PaymentStageStatus.DONE,
    ).exists()


class PaymentConfirmService:

    def __init__(self):
        self.stages = StageService()

    # --- confirm ----------------------------------------------------------

    @transaction.atomic
    def confirm_batch(self, *, user, batch_id, authorization_text, meta):
        batch = PaymentBatch.objects.filter(id=batch_id, user=user).first()

        if batch is None:
            raise ValidationError({"batch": "Batch not found."})

        # of=("self",) because vendor is nullable, so select_related emits
        # a LEFT JOIN and Postgres refuses FOR UPDATE on its nullable side.
        payments = list(
            batch.payments.select_related("vendor").select_for_update(
                of=("self",)
            )
        )

        if not payments:
            raise ValidationError({"batch": "Batch has no payments."})

        # One authorization per batch. A repeat confirm must not mint a second
        # consent record for the same act of consenting.
        if batch.authorizations.exists():
            return {"batch": batch, "payments": payments, "replayed": True}

        self._record(
            authorization_text=authorization_text,
            meta=meta,
            batch=batch,
        )

        for payment in payments:
            self._advance(payment)

        return {"batch": batch, "payments": payments, "replayed": False}

    @transaction.atomic
    def confirm_payment(self, *, user, payment_id, authorization_text, meta):
        payment = (
            Payment.objects.select_for_update()
            .filter(id=payment_id, user=user)
            .first()
        )

        if payment is None:
            raise ValidationError({"payment": "Payment not found."})

        if payment.batch_id:
            raise ValidationError(
                {
                    "payment": (
                        "This payment belongs to a batch; confirm the batch "
                        "instead so one consent covers all of it."
                    )
                }
            )

        if payment.authorizations.exists():
            return {"payment": payment, "replayed": True}

        self._record(
            authorization_text=authorization_text,
            meta=meta,
            payment=payment,
        )

        self._advance(payment)

        return {"payment": payment, "replayed": False}

    def _record(self, *, authorization_text, meta, payment=None, batch=None):
        text = (authorization_text or "").strip()

        if not text:
            raise ValidationError(
                {
                    "authorization_text": (
                        "The authorization text shown to the user is required."
                    )
                }
            )

        ip = (meta or {}).get("ip")

        if not ip:
            # Better to refuse than to file consent against a placeholder.
            raise ValidationError(
                {
                    "authorization_text": (
                        "Could not determine the client IP address, so the "
                        "authorization cannot be recorded."
                    )
                }
            )

        return PaymentAuthorization.objects.create(
            payment=payment,
            batch=batch,
            authorization_text=text,
            accepted_at=timezone.now(),
            ip=ip,
            user_agent=(meta or {}).get("user_agent", ""),
        )

    def _advance(self, payment):
        """Move a confirmed payment towards execution."""
        if payment.status not in CONFIRMABLE:
            raise ValidationError(
                {
                    "payment": (
                        f"Payment {payment.transaction_reference} cannot be "
                        f"confirmed from {payment.status}."
                    )
                }
            )

        self.stages.seed(payment)
        self.stages.mark(
            payment, PaymentStageName.AUTHORIZED, PaymentStageStatus.DONE
        )

        # A future-dated payment stays SCHEDULED until its send date; the beat
        # job picks it up. Everything else goes now.
        if payment.scheduled_for:
            payment.status = PaymentStatus.SCHEDULED
            payment.save(update_fields=["status", "updated_at"])
            return payment

        payment.status = PaymentStatus.PROCESSING
        payment.save(update_fields=["status", "updated_at"])

        from apps.payments.tasks import execute_payment

        transaction.on_commit(
            lambda: execute_payment.delay(payment_id=str(payment.id))
        )

        return payment

    # --- cancel (E6-S5) ---------------------------------------------------

    @transaction.atomic
    def cancel_payment(self, *, user, payment_id, now=None):
        payment = (
            Payment.objects.select_for_update()
            .filter(id=payment_id, user=user)
            .first()
        )

        if payment is None:
            raise ValidationError({"payment": "Payment not found."})

        return self._cancel_one(payment, now=now)

    @transaction.atomic
    def cancel_batch(self, *, user, batch_id, now=None):
        batch = PaymentBatch.objects.filter(id=batch_id, user=user).first()

        if batch is None:
            raise ValidationError({"batch": "Batch not found."})

        payments = list(batch.payments.select_for_update())

        cancelled = [
            self._cancel_one(payment, now=now)
            for payment in payments
            if payment.status in CANCELLABLE
        ]

        if not cancelled:
            raise ConflictException(
                "No payments in this batch can still be cancelled."
            )

        return {"batch": batch, "cancelled": cancelled}

    def expire_unconfirmed(self, *, older_than):
        """Cancel payments nobody confirmed in time; returns how many (PAY-1).

        Creating a payment reserves its bill (the occurrence goes SCHEDULED
        so reminders stop). If the user never confirms, that reservation
        would strand the bill, so it lapses.
        """
        stale = (
            Payment.objects.filter(
                status__in=CONFIRMABLE, created_at__lt=older_than
            )
            .exclude(
                stages__stage=PaymentStageName.AUTHORIZED,
                stages__status=PaymentStageStatus.DONE,
            )
            .values_list("id", flat=True)
        )

        expired = 0

        for payment_id in list(stale):
            with transaction.atomic():
                payment = (
                    Payment.objects.select_for_update()
                    .filter(id=payment_id, status__in=CONFIRMABLE)
                    .first()
                )

                # Re-checked under the lock: it may have been confirmed or
                # cancelled since the list was read.
                if payment is None or is_confirmed(payment):
                    continue

                self._cancel_one(
                    payment, detail="Not confirmed in time"
                )
                expired += 1

        return expired

    def _cancel_one(self, payment, now=None, detail="Cancelled by user"):
        now = now or timezone.now()

        if payment.status not in CANCELLABLE:
            raise ConflictException(
                f"Payment {payment.transaction_reference} is "
                f"{payment.status} and can no longer be cancelled."
            )

        # The deadline protects money the user has authorized to move. An
        # unconfirmed payment has moved nothing and authorized nothing, so it
        # can always be cancelled (PAY-1). Before, a pay-now payment's
        # deadline had passed before it was even created, so one abandoned
        # at the confirm screen could never be cancelled and its bill stayed
        # SCHEDULED for good.
        if (
            is_confirmed(payment)
            and payment.cancellation_deadline
            and now > payment.cancellation_deadline
        ):
            raise ConflictException(
                "The cancellation window for "
                f"{payment.transaction_reference} has closed."
            )

        # If it already reached the processor, void it there too — marking it
        # cancelled locally while money moves would be a lie.
        if payment.provider_reference:
            self._void_at_processor(payment)

        payment.status = PaymentStatus.CANCELLED
        payment.save(update_fields=["status", "updated_at"])

        self.stages.fail(payment, detail=detail)

        self._release_occurrence(payment)

        return payment

    def _void_at_processor(self, payment):
        from integrations.factory import get_money_movement_provider

        provider = get_money_movement_provider()
        void = getattr(provider, "void", None)

        if callable(void):
            void(reference=payment.transaction_reference)

    def _release_occurrence(self, payment):
        """Hand the occurrence back so it is payable again."""
        from apps.bills.selectors.occurrence_status import (
            TERMINAL_STATUSES,
        )
        from apps.common.enums import BillOccurrenceStatus

        occurrence = payment.bill_occurrence

        if occurrence is None:
            return

        if occurrence.status in TERMINAL_STATUSES and (
            occurrence.status != BillOccurrenceStatus.SCHEDULED
        ):
            # Already paid — nothing to release.
            return

        occurrence.status = BillOccurrenceStatus.UPCOMING
        occurrence.save(update_fields=["status", "updated_at"])
