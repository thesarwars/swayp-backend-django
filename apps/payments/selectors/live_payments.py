"""Which occurrences already have money moving (the E6-S9 contract).

One definition, because "is this occurrence handled?" is asked from four
places and a second opinion is a duplicate payment or a duplicate reminder.
"""

from apps.common.enums import PaymentStatus
from apps.payments.models import Payment

#: One live payment per occurrence — the set E6-S9 guards *creation* with.
IN_FLIGHT_PAYMENT_STATUSES = (
    PaymentStatus.SCHEDULED,
    PaymentStatus.PENDING,
    PaymentStatus.PROCESSING,
)

#: Statuses that silence a reminder: the in-flight set plus SUCCESSFUL,
#: because a settled occurrence must not be nagged either. Carried over from
#: the ReminderService E8-S4 removed rather than re-derived.
SILENCING_PAYMENT_STATUSES = IN_FLIGHT_PAYMENT_STATUSES + (
    PaymentStatus.SUCCESSFUL,
)


def occurrence_ids_with_live_payment(occurrence_ids):
    """Ids from ``occurrence_ids`` that already have a silencing payment.

    One query for the whole batch. The per-occurrence ``.exists()`` the old
    ReminderService did was one query per row.
    """
    if not occurrence_ids:
        return set()

    return set(
        Payment.objects.filter(
            bill_occurrence_id__in=occurrence_ids,
            status__in=SILENCING_PAYMENT_STATUSES,
        ).values_list("bill_occurrence_id", flat=True)
    )
