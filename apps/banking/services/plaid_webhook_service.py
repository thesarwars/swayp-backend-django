"""What Plaid's callbacks mean for a scan (E5).

Plaid pulls an item's history asynchronously after it is linked, so the scan
started at connect time reaches for data that has not arrived and stops with
``BankDataNotReady`` — the scan stays RUNNING and waits. This is what wakes it.

Without it the first scan of every connection is a race against Plaid's
backfill, and losing that race is silent: a fresh item answers with whatever
has landed so far and no error, so detection runs over a month of history
instead of two years and reports a near-empty result that looks like an
answer.

``TRANSACTIONS/HISTORICAL_UPDATE`` is the signal that the full window is
ready. ``INITIAL_UPDATE`` fires earlier with only the last 30 days, which is
exactly the partial state worth *not* acting on.
"""

import logging

from django.db import transaction

from apps.banking.models import BankConnection, TransactionScan
from apps.common.enums import ScanStatus

logger = logging.getLogger(__name__)

RESULT_RESUMED = "scan_resumed"
RESULT_STARTED = "scan_started"
RESULT_IGNORED = "ignored"
RESULT_UNKNOWN_ITEM = "unknown_item"

#: The codes that mean "the history you asked for is now there".
_READY_CODES = {"HISTORICAL_UPDATE"}

#: Recorded and acknowledged, but acted on by nothing. Named rather than
#: lumped in with the unknown so the log says "we know, and we are waiting".
_KNOWN_BUT_IGNORED = {
    "INITIAL_UPDATE",          # 30 days only — acting on it is the bug
    "DEFAULT_UPDATE",          # incremental, after the first scan
    "TRANSACTIONS_REMOVED",
    "SYNC_UPDATES_AVAILABLE",
}


class PlaidWebhookService:

    def handle(self, payload):
        code = payload.get("webhook_code") or ""
        item_id = payload.get("item_id") or ""

        if code not in _READY_CODES:
            if code not in _KNOWN_BUT_IGNORED:
                logger.info("unhandled Plaid webhook code %r", code)

            return RESULT_IGNORED

        connection = BankConnection.objects.filter(item_id=item_id).first()

        if connection is None:
            # Not an error worth retrying: an item removed on our side still
            # emits callbacks for a while. Acknowledged so Plaid stops.
            logger.warning("Plaid webhook for unknown item %s", item_id)

            return RESULT_UNKNOWN_ITEM

        return self.resume(connection)

    def resume(self, connection):
        """Re-queue the scan that was waiting, or start one if none is.

        Re-queues rather than runs: the work belongs on the same Celery task
        the connect path uses, so a slow history pull cannot hold a webhook
        response open — and a processor that does not get a prompt 200
        retries.
        """
        scan = (
            TransactionScan.objects.filter(
                connection=connection, status=ScanStatus.RUNNING
            )
            .order_by("-created_at")
            .first()
        )

        result = RESULT_RESUMED

        if scan is None:
            # No scan waiting. The history is ready and nobody asked for it,
            # which happens when the connect-time scan already failed for
            # another reason. Starting one is better than dropping the event.
            scan = TransactionScan.objects.create(
                connection=connection, status=ScanStatus.RUNNING
            )
            result = RESULT_STARTED

        from apps.banking.tasks import sync_transactions

        transaction.on_commit(
            lambda: sync_transactions.delay(scan_id=str(scan.id))
        )

        logger.info(
            "Plaid history ready for item %s; %s scan %s",
            connection.item_id,
            result,
            scan.pk,
        )

        return result
