"""Banking background work (E5-S4)."""

import logging

from celery import shared_task

logger = logging.getLogger(__name__)


@shared_task(name="banking.sync_transactions", bind=True, max_retries=2)
def sync_transactions(self, *, scan_id):
    """Pull history for a scan and detect recurring bills.

    Failures mark the scan FAILED before re-raising, so the polling endpoint
    reports the failure instead of showing RUNNING forever.
    """
    from apps.banking.models import TransactionScan
    from apps.banking.services.scan_service import ScanService

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

    logger.info(
        "scan %s detected %s candidates from %s transactions",
        scan.pk,
        scan.detected_count,
        scan.transactions_scanned,
    )

    return scan.detected_count
