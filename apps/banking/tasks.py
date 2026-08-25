"""Banking background work (E5-S4)."""

import logging

from celery import shared_task

logger = logging.getLogger(__name__)

#: How long to keep asking Plaid for history that has not arrived.
#:
#: The webhook (TRANSACTIONS/HISTORICAL_UPDATE) is the proper signal and
#: resumes the scan the moment the data lands. This is the fallback for when
#: it never comes — PLAID_WEBHOOK_URL unset, an item linked before it was
#: configured, a lost delivery — because without it such a scan sits RUNNING
#: forever and the progress screen spins with nothing behind it.
#:
#: Backs off 30s, 60s, 120s… to roughly 30 minutes, which is beyond what a
#: backfill takes. Past that the scan is marked FAILED with something a person
#: can read, rather than left spinning.
NOT_READY_MAX_RETRIES = 7
NOT_READY_BASE_DELAY_SECONDS = 30


@shared_task(name="banking.sync_transactions", bind=True, max_retries=2)
def sync_transactions(self, *, scan_id):
    """Pull history for a scan and detect recurring bills.

    Failures mark the scan FAILED before re-raising, so the polling endpoint
    reports the failure instead of showing RUNNING forever.
    """
    from apps.banking.models import TransactionScan
    from apps.banking.services.scan_service import ScanService
    from apps.common.enums import ScanStatus

    scan = TransactionScan.objects.select_related("connection").filter(
        id=scan_id
    ).first()

    if scan is None:
        logger.warning("sync_transactions: scan %s no longer exists", scan_id)
        return 0

    try:
        ScanService().run(scan)
    except Exception as exc:
        if self.request.retries >= self.max_retries:
            raise
        raise self.retry(exc=exc, countdown=5 * (self.request.retries + 1))

    scan.refresh_from_db()

    # Still RUNNING after a clean run means the provider had nothing to give
    # yet — run() leaves every other outcome as DONE or FAILED. Ask again
    # rather than wait on a webhook that may never be configured.
    if scan.status == ScanStatus.RUNNING:
        return _retry_until_ready(self, scan)

    logger.info(
        "scan %s detected %s candidates from %s transactions",
        scan.pk,
        scan.detected_count,
        scan.transactions_scanned,
    )

    return scan.detected_count


def _retry_until_ready(task, scan):
    """Re-queue a waiting scan, or give up in a way somebody can act on."""
    from django.utils import timezone

    from apps.common.enums import ScanStatus

    attempt = task.request.retries

    if attempt >= NOT_READY_MAX_RETRIES:
        logger.error(
            "scan %s: provider history never arrived after %s attempts",
            scan.pk,
            attempt,
        )

        scan.status = ScanStatus.FAILED
        scan.error_message = (
            "Your bank is still preparing your transaction history. "
            "Try scanning again in a few minutes."
        )
        scan.completed_at = timezone.now()
        scan.save(
            update_fields=[
                "status",
                "error_message",
                "completed_at",
                "updated_at",
            ]
        )

        return 0

    countdown = NOT_READY_BASE_DELAY_SECONDS * (2**attempt)

    logger.info(
        "scan %s: history not ready, asking again in %ss (attempt %s)",
        scan.pk,
        countdown,
        attempt + 1,
    )

    # max_retries is passed explicitly: the task-level 2 is for genuine
    # failures, and waiting for a backfill needs far more patience than
    # retrying a broken call.
    raise task.retry(
        countdown=countdown, max_retries=NOT_READY_MAX_RETRIES
    )
