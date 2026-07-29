"""Read-time occurrence status (E4-S1 / E4-S2).

`BillOccurrence.status` stores only the **payment-driven** states — an
occurrence becomes SCHEDULED or PAID because a payment moved it there. The
**time-driven** states (UPCOMING / DUE / OVERDUE) are never written: they are
derived from `due_date` every time a row is read.

That split is what the epic's "no stored status" decision buys us. A beat job
that stamped OVERDUE nightly would leave a bill due *today* reading UPCOMING
until the next tick; annotating instead means the transition happens the
moment the clock does.
"""

from django.db.models import Case, CharField, F, Value, When

from apps.common.dates import today_eastern
from apps.common.enums import BillOccurrenceStatus

#: Stored states that win over anything the calendar would say.
TERMINAL_STATUSES = (
    BillOccurrenceStatus.SCHEDULED,
    BillOccurrenceStatus.PAID,
)


def status_expression(today=None):
    """Case/When yielding the effective status of an occurrence."""
    today = today or today_eastern()

    return Case(
        When(status__in=TERMINAL_STATUSES, then=F("status")),
        When(due_date__lt=today, then=Value(BillOccurrenceStatus.OVERDUE)),
        When(due_date=today, then=Value(BillOccurrenceStatus.DUE)),
        default=Value(BillOccurrenceStatus.UPCOMING),
        output_field=CharField(),
    )


def annotate_status(queryset, today=None):
    """Attach ``computed_status`` to every row of ``queryset``."""
    return queryset.annotate(
        computed_status=status_expression(today),
    )


def open_occurrences(queryset):
    """Occurrences still awaiting payment (not SCHEDULED, not PAID)."""
    return queryset.exclude(status__in=TERMINAL_STATUSES)
