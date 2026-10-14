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



def _destination(payment):
    from apps.payments.services.rails import describe_method, method_for_bill

    occurrence = payment.bill_occurrence
    method = method_for_bill(occurrence.bill) if occurrence else None
    described = describe_method(method)

    return {
        "payment_method_type": described["type"],
        "account_ref": described["account_ref"],
    }

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

    def authorization(self, payment):
        """Who approved this payment, with what words, and when (PAY-1).

        Memoised on the instance: the serializer reads three fields from it.
        The text is the per-payment consent, else the batch's, else the
        bill's standing authorization for an autopay payment.
        """
        cached = getattr(payment, "_authorization_cache", None)

        if cached is not None:
            return cached

        from datetime import timedelta

        from django.conf import settings

        from apps.common.enums import PaymentStageStatus
        from apps.payments.models import PaymentStageName

        stage = payment.stages.filter(
            stage=PaymentStageName.AUTHORIZED,
            status=PaymentStageStatus.DONE,
        ).first()

        text = None

        if stage is not None:
            consent = payment.authorizations.order_by("-accepted_at").first()

            if consent is None and payment.batch_id:
                consent = payment.batch.authorizations.order_by(
                    "-accepted_at"
                ).first()

            if consent is None and payment.bill_occurrence_id:
                consent = (
                    payment.bill_occurrence.bill.standing_authorizations.filter(
                        revoked_at__isnull=True
                    )
                    .order_by("-accepted_at")
                    .first()
                )

            text = consent.authorization_text if consent else None

        confirm_by = None

        if stage is None and payment.status in (
            PaymentStatus.SCHEDULED,
            PaymentStatus.PENDING,
        ):
            confirm_by = payment.created_at + timedelta(
                minutes=getattr(settings, "PAYMENT_CONFIRM_TIMEOUT_MINUTES", 30)
            )

        result = {
            "authorized_at": stage.finished_at if stage else None,
            "authorization_text": text,
            "confirm_by": confirm_by,
        }

        payment._authorization_cache = result

        return result

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
            # "Sent to ACH ****4821" (web C9).
            **_destination(payment),
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
