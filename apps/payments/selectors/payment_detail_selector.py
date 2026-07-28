"""Read-side queries for payment status and detail (E6-S4)."""

from apps.common.enums import PaymentStageStatus, PaymentStatus
from apps.payments.models import Payment, PaymentBatch

_RELATED = (
    "vendor",
    "funding_account",
    "batch",
    "bill_occurrence",
    "bill_occurrence__bill",
)


class PaymentDetailSelector:

    def get_payment(self, user, payment_id):
        return (
            Payment.objects.filter(id=payment_id, user=user)
            .select_related(*_RELATED)
            .prefetch_related("stages")
            .first()
        )

    def get_batch(self, user, batch_id):
        return (
            PaymentBatch.objects.filter(id=batch_id, user=user)
            .prefetch_related("payments__stages", "payments__vendor")
            .first()
        )

    def batch_status(self, batch):
        """Aggregate a batch from its payments' stages.

        The batch is only as far along as its least-advanced payment, so a
        single failure surfaces rather than being averaged away.
        """
        payments = list(batch.payments.all())
        statuses = {p.status for p in payments}

        if PaymentStatus.FAILED in statuses:
            overall = PaymentStatus.FAILED
        elif statuses and statuses <= {PaymentStatus.SUCCESSFUL}:
            overall = PaymentStatus.SUCCESSFUL
        elif PaymentStatus.PROCESSING in statuses:
            overall = PaymentStatus.PROCESSING
        elif statuses == {PaymentStatus.CANCELLED}:
            overall = PaymentStatus.CANCELLED
        else:
            overall = PaymentStatus.PENDING

        return {
            "batch_id": batch.id,
            "status": overall,
            "total": batch.total,
            "count": batch.count,
            "succeeded": sum(
                1 for p in payments if p.status == PaymentStatus.SUCCESSFUL
            ),
            "failed": sum(
                1 for p in payments if p.status == PaymentStatus.FAILED
            ),
            "in_flight": sum(1 for p in payments if p.is_in_flight),
            "payments": payments,
        }

    def receipt(self, payment):
        """Receipt fields for a settled payment (840:28867)."""
        if payment.status != PaymentStatus.SUCCESSFUL:
            return None

        account = payment.funding_account

        return {
            "recipient": payment.vendor.name if payment.vendor else None,
            "amount": payment.total,
            "funding_account": account.masked_name if account else None,
            "estimated_arrival": payment.estimated_arrival,
            "reference": payment.transaction_reference,
            "paid_on": payment.updated_at,
        }

    def failure_block(self, payment):
        if payment.status not in (
            PaymentStatus.FAILED,
            PaymentStatus.RETURNED,
        ):
            return None

        return {
            "reason": payment.failure_reason,
            "detail": payment.failure_detail,
            "can_resolve": payment.status == PaymentStatus.FAILED,
        }

    def progress(self, payment):
        stages = list(payment.stages.order_by("order"))
        done = sum(
            1 for s in stages if s.status == PaymentStageStatus.DONE
        )

        return {
            "completed": done,
            "total": len(stages),
            "is_complete": payment.is_terminal,
        }
