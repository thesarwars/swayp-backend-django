"""Payment background work (E6-S7 / E6-S9)."""

import logging

from celery import shared_task

logger = logging.getLogger(__name__)


@shared_task(name="payments.execute_payment", bind=True, max_retries=3)
def execute_payment(self, *, payment_id):
    """Run one payment through the processor.

    An ambiguous failure — submitted, outcome unknown — is retried, but the
    engine looks the transfer up by idempotency key before re-sending, so a
    retry can never produce a second debit.
    """
    from apps.payments.services.execution_service import (
        PaymentExecutionService,
    )

    try:
        payment = PaymentExecutionService().execute(payment_id)
    except Exception as exc:
        logger.warning("execute_payment %s failed: %s", payment_id, exc)

        if self.request.retries >= self.max_retries:
            raise

        raise self.retry(exc=exc, countdown=10 * (self.request.retries + 1))

    if payment is None:
        return None

    return payment.status


@shared_task(name="payments.reconcile_payments")
def reconcile_payments():
    """Hourly sweep: close payments the processor never reported back on."""
    from apps.payments.services.execution_service import (
        PaymentExecutionService,
    )

    closed = PaymentExecutionService().reconcile()

    logger.info("reconcile_payments closed %s stuck payment(s)", closed)

    return closed


@shared_task(name="payments.release_scheduled_payments")
def release_scheduled_payments():
    """Send future-dated payments whose date has arrived (E6-S2)."""
    from django.utils import timezone

    from apps.common.enums import PaymentStatus
    from apps.payments.models import Payment

    today = timezone.localdate()

    due = Payment.objects.filter(
        status=PaymentStatus.SCHEDULED,
        scheduled_for__lte=today,
    ).values_list("id", flat=True)

    released = 0

    for payment_id in due:
        # Only confirmed payments carry an authorization; an unconfirmed
        # SCHEDULED payment must not start moving money on its own.
        from apps.payments.models import Payment as PaymentModel

        payment = PaymentModel.objects.get(pk=payment_id)

        if not _has_authorization(payment):
            logger.warning(
                "release: %s is due but has no authorization",
                payment.transaction_reference,
            )
            continue

        payment.status = PaymentStatus.PROCESSING
        payment.save(update_fields=["status", "updated_at"])

        execute_payment.delay(payment_id=str(payment.id))
        released += 1

    logger.info("release_scheduled_payments released %s", released)

    return released


def _has_authorization(payment):
    if payment.authorizations.exists():
        return True

    if payment.batch_id and payment.batch.authorizations.exists():
        return True

    # Autopay payments are covered by the bill's standing authorization.
    occurrence = payment.bill_occurrence

    if occurrence and occurrence.bill_id:
        return occurrence.bill.standing_authorizations.filter(
            revoked_at__isnull=True
        ).exists()

    return False


@shared_task(name="payments.autopay_scheduler")
def autopay_scheduler():
    """Create payments for AUTO bills at their lead time (E6-S9)."""
    from apps.payments.services.autopay_service import AutopayService

    report = AutopayService().run()

    logger.info(
        "autopay_scheduler created=%s skipped=%s unauthorized=%s",
        report["created"],
        report["skipped"],
        report["unauthorized"],
    )

    return report["created"]
