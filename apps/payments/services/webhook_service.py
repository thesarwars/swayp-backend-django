"""Processor webhooks (E6-S8).

Processors redeliver and reorder, so every handler here is written to be
applied more than once and out of sequence without harm:

- the event is recorded first, and a conflicting insert means "already seen";
- the payment is locked before its state is touched;
- a transition that is already satisfied is a no-op, not an error.

A **late return** is the case worth understanding: ACH can claw money back days
after it settled. That takes a SUCCESSFUL payment to RETURNED and puts the
occurrence back to unpaid, because the vendor no longer has the money.
"""

import hashlib
import hmac
import logging

from django.db import IntegrityError, transaction
from django.utils import timezone

from apps.common.enums import (
    BillOccurrenceStatus,
    PaymentStageStatus,
    PaymentStatus,
)
from apps.payments.models import Payment, PaymentStageName, WebhookEvent
from apps.payments.services.stage_service import StageService

logger = logging.getLogger(__name__)

#: Event type -> resulting payment status.
EVENT_STATUS = {
    "transfer.completed": PaymentStatus.SUCCESSFUL,
    "transfer.succeeded": PaymentStatus.SUCCESSFUL,
    "transfer.failed": PaymentStatus.FAILED,
    "transfer.returned": PaymentStatus.RETURNED,
    "transfer.cancelled": PaymentStatus.CANCELLED,
}

RESULT_APPLIED = "applied"
RESULT_DUPLICATE = "duplicate"
RESULT_IGNORED = "ignored"
RESULT_UNKNOWN_PAYMENT = "unknown_payment"


class SignatureError(Exception):
    """The payload did not carry a valid signature for this processor."""


def verify_signature(*, processor, raw_body, signature, secret):
    """HMAC-SHA256 over the raw body.

    The raw body matters: re-serializing parsed JSON changes key order and
    whitespace, and the signature would never match.
    """
    if not secret:
        # No secret configured means we cannot prove anything about the
        # sender, so refuse rather than trust it.
        raise SignatureError(
            f"No webhook secret configured for {processor}."
        )

    if not signature:
        raise SignatureError("Missing signature header.")

    expected = hmac.new(
        secret.encode(), raw_body, hashlib.sha256
    ).hexdigest()

    if not hmac.compare_digest(expected, signature):
        raise SignatureError("Signature mismatch.")

    return True


class WebhookService:

    def __init__(self):
        self.stages = StageService()

    def record(self, *, processor, event_id, event_type, payload):
        """Insert-or-skip. Returns (event, is_new)."""
        try:
            with transaction.atomic():
                event = WebhookEvent.objects.create(
                    processor=processor,
                    event_id=event_id,
                    event_type=event_type or "",
                    payload=payload or {},
                )

            return event, True
        except IntegrityError:
            existing = WebhookEvent.objects.get(
                processor=processor, event_id=event_id
            )

            return existing, False

    def handle(self, *, processor, event_id, event_type, payload):
        event, is_new = self.record(
            processor=processor,
            event_id=event_id,
            event_type=event_type,
            payload=payload,
        )

        if not is_new:
            logger.info("webhook %s:%s already seen", processor, event_id)
            return RESULT_DUPLICATE

        result = self._apply(event)

        event.processed_at = timezone.now()
        event.result = result
        event.save(update_fields=["processed_at", "result", "updated_at"])

        return result

    @transaction.atomic
    def _apply(self, event):
        payload = event.payload or {}
        reference = payload.get("reference") or payload.get(
            "transaction_reference"
        )

        if not reference:
            return RESULT_IGNORED

        payment = (
            Payment.objects.select_for_update()
            .filter(transaction_reference=reference)
            .first()
        )

        if payment is None:
            logger.warning("webhook references unknown payment %s", reference)
            return RESULT_UNKNOWN_PAYMENT

        target = EVENT_STATUS.get(event.event_type)

        if target is None:
            return RESULT_IGNORED

        if payment.status == target:
            # Redelivery or a race with the execution engine.
            return RESULT_DUPLICATE

        if target == PaymentStatus.RETURNED:
            return self._apply_return(payment, payload)

        if target == PaymentStatus.SUCCESSFUL:
            return self._apply_success(payment, payload)

        if target == PaymentStatus.FAILED:
            return self._apply_failure(payment, payload)

        if target == PaymentStatus.CANCELLED:
            return self._apply_cancel(payment)

        return RESULT_IGNORED

    def _apply_success(self, payment, payload):
        if payment.is_terminal:
            # Out-of-order: a later event already closed this out.
            return RESULT_IGNORED

        payment.status = PaymentStatus.SUCCESSFUL
        payment.provider_reference = (
            payload.get("provider_reference") or payment.provider_reference
        )
        payment.save(
            update_fields=["status", "provider_reference", "updated_at"]
        )

        self.stages.mark(
            payment, PaymentStageName.COMPLETED, PaymentStageStatus.DONE
        )
        self._set_occurrence(
            payment,
            BillOccurrenceStatus.PAID,
            paid_at=timezone.now(),
            reference=payment.transaction_reference,
        )

        return RESULT_APPLIED

    def _apply_failure(self, payment, payload):
        if payment.is_terminal:
            return RESULT_IGNORED

        payment.status = PaymentStatus.FAILED
        payment.failure_reason = payload.get("reason", "PROCESSOR_DECLINED")
        payment.failure_detail = payload.get("detail", {}) or {}
        payment.save(
            update_fields=[
                "status",
                "failure_reason",
                "failure_detail",
                "updated_at",
            ]
        )

        self.stages.fail(payment, detail=payment.failure_reason)
        self._set_occurrence(payment, BillOccurrenceStatus.UPCOMING)

        return RESULT_APPLIED

    def _apply_return(self, payment, payload):
        """A late ACH return — money the vendor already had is clawed back.

        Only a SUCCESSFUL payment can be returned; anything else never
        settled, so there is nothing to reverse.
        """
        if payment.status != PaymentStatus.SUCCESSFUL:
            return RESULT_IGNORED

        payment.status = PaymentStatus.RETURNED
        payment.failure_reason = payload.get("reason", "ACH_RETURN")
        payment.failure_detail = payload.get("detail", {}) or {}
        payment.save(
            update_fields=[
                "status",
                "failure_reason",
                "failure_detail",
                "updated_at",
            ]
        )

        self.stages.mark(
            payment,
            PaymentStageName.COMPLETED,
            PaymentStageStatus.FAILED,
            detail="Returned by the receiving bank",
        )

        # The bill is owed again — DUE rather than PAID.
        self._set_occurrence(
            payment, BillOccurrenceStatus.UPCOMING, clear_payment=True
        )

        self._notify(
            payment,
            "Payment returned",
            (
                f"{payment.transaction_reference} was returned by the bank. "
                "The bill is outstanding again."
            ),
        )

        return RESULT_APPLIED

    def _apply_cancel(self, payment):
        if payment.is_terminal:
            return RESULT_IGNORED

        payment.status = PaymentStatus.CANCELLED
        payment.save(update_fields=["status", "updated_at"])

        self.stages.fail(payment, detail="Cancelled at the processor")
        self._set_occurrence(payment, BillOccurrenceStatus.UPCOMING)

        return RESULT_APPLIED

    def _set_occurrence(self, payment, status, paid_at=None, reference=None,
                        clear_payment=False):
        from apps.bills.models.bill_occurrence import BillOccurrence

        if not payment.bill_occurrence_id:
            return

        fields = {"status": status}

        if paid_at is not None:
            fields["paid_at"] = paid_at

        if reference is not None:
            fields["payment_reference"] = reference

        if clear_payment:
            fields["paid_at"] = None
            fields["payment_reference"] = ""

        BillOccurrence.objects.filter(pk=payment.bill_occurrence_id).update(
            **fields
        )

    def _notify(self, payment, title, message):
        from apps.notifications.models import Notification

        Notification.objects.create(
            user=payment.user,
            title=title,
            message=message,
            type="PAYMENT",
            metadata={"payment_id": str(payment.id)},
        )
