"""Bill occurrence engine (E4-S6).

Daily beat job. Keeps every bill stocked with occurrences out to the horizon
so the list, summary and next-due screens always have rows to read. Safe to
re-run: generation skips due dates that already exist.
"""

import logging

from celery import shared_task
from django.utils import timezone

from apps.bills.models.bill import Bill
from apps.bills.services.bill_occurrence_service import BillOccurrenceService

logger = logging.getLogger(__name__)


@shared_task(name="bills.generate_occurrences")
def generate_occurrences():
    """Roll every bill's occurrences forward. Returns rows created."""
    service = BillOccurrenceService()
    today = timezone.localdate()

    created = 0
    failed = 0

    queryset = Bill.objects.select_related("vendor").order_by("created_at")

    for bill in queryset.iterator():
        try:
            created += len(service.generate_occurrences(bill, today=today))
        except Exception:
            # One malformed bill must not stop the rest of the run.
            failed += 1
            logger.exception(
                "generate_occurrences failed for bill %s", bill.pk
            )

    logger.info(
        "generate_occurrences: created=%s failed=%s", created, failed
    )

    return created
