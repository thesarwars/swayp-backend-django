from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from apps.bills.models.bill_occurrence import BillOccurrence
from apps.bills.selectors.bill_occurrence_selector import BillOccurrenceSelector
from apps.bills.selectors.occurrence_status import open_occurrences
from apps.common.dates import next_occurrence
from apps.common.enums import (
    BillFrequency,
    BillOccurrenceStatus,
    BillType,
)


class BillOccurrenceService:
    """Materialises a Bill's recurrence rule into concrete occurrences."""

    #: How far past the current period to keep occurrences pre-created (E4-S6).
    HORIZON_CYCLES = 2

    #: Safety valve for a bill anchored implausibly far in the past.
    MAX_CATCHUP_CYCLES = 1200

    #: Safety valve for forecasting forward (see ``due_dates_through``). A
    #: weekly bill needs ~52 steps per year; the projection endpoint caps the
    #: requested date long before this is reached.
    MAX_FORECAST_CYCLES = 1200

    def __init__(self):
        self.selector = BillOccurrenceSelector()

    # --- generation -------------------------------------------------------

    @transaction.atomic
    def generate_occurrences(self, bill, today=None):
        """Create any missing occurrences for ``bill`` within the horizon.

        Idempotent: existing due dates are skipped, and the unique constraint
        on (bill, due_date) absorbs anything a concurrent run slips in.
        """
        today = today or timezone.localdate()

        due_dates = self.horizon_due_dates(bill, today)

        existing = set(
            BillOccurrence.objects.filter(
                bill=bill,
                due_date__in=due_dates,
            ).values_list("due_date", flat=True)
        )

        missing = [
            BillOccurrence(
                bill=bill,
                due_date=due_date,
                amount=bill.amount,
                status=BillOccurrenceStatus.UPCOMING,
            )
            for due_date in due_dates
            if due_date not in existing
        ]

        if missing:
            BillOccurrence.objects.bulk_create(
                missing,
                ignore_conflicts=True,
            )

        return missing

    def horizon_due_dates(self, bill, today=None):
        """Due dates that should exist right now for ``bill``.

        The current period plus ``HORIZON_CYCLES`` ahead. Recurrence maths is
        delegated to ``apps.common.dates.next_occurrence`` so month-end
        clamping (Jan 31 -> Feb 28 -> Mar 31, not Mar 28), weekday-preserving
        weeklies and quarterly anchor cadence stay in one place.
        """
        today = today or timezone.localdate()
        anchor = bill.anchor_date

        # A one-time bill has exactly one occurrence, ever. next_occurrence
        # returns the anchor unconditionally for ONE_TIME, so walking it would
        # spin forever on the same date.
        if bill.frequency == BillFrequency.ONE_TIME:
            return [anchor]

        current = self._current_period_start(anchor, bill.frequency, today)

        due_dates = [current]
        cursor = current

        for _ in range(self.HORIZON_CYCLES):
            cursor = next_occurrence(anchor, bill.frequency, after=cursor)
            due_dates.append(cursor)

        return due_dates

    def due_dates_through(self, bill, through, today=None):
        """Due dates this bill's rule produces in ``[today, through]``.

        ``horizon_due_dates`` answers "what rows should exist right now" and
        stops two cycles out (E4-S6). A forecast asks a different question —
        "what comes due by date X" — and X is routinely past that horizon: a
        weekly bill is only materialised ~13 days ahead, so a 90-day balance
        projection built from rows alone silently subtracts nothing for it.

        This walks the recurrence rule instead, read-only: nothing is created,
        so a GET stays a GET and the answer is exact past the horizon. Cadence
        maths stays delegated to ``apps.common.dates.next_occurrence``, so
        month-end clamping and weekday-preserving weeklies behave identically
        to the rows the beat job will eventually write.
        """
        today = today or timezone.localdate()

        if through < today:
            return []

        anchor = bill.anchor_date

        # A one-time bill has exactly one due date, ever.
        if bill.frequency == BillFrequency.ONE_TIME:
            return [anchor] if today <= anchor <= through else []

        cursor = self._current_period_start(anchor, bill.frequency, today)

        due_dates = []

        if today <= cursor <= through:
            due_dates.append(cursor)

        for _ in range(self.MAX_FORECAST_CYCLES):
            cursor = next_occurrence(anchor, bill.frequency, after=cursor)

            if cursor > through:
                break

            if cursor >= today:
                due_dates.append(cursor)

        return due_dates

    def _current_period_start(self, anchor, frequency, today):
        """Latest due date on or before ``today``; the anchor if it is future.

        Bills anchored in the past land on their current unpaid period rather
        than backfilling every cycle since the anchor — the daily beat keeps
        the horizon stocked, so nothing legitimately due ever goes missing.
        """
        current = anchor

        for _ in range(self.MAX_CATCHUP_CYCLES):
            candidate = next_occurrence(anchor, frequency, after=current)

            if candidate > today:
                break

            current = candidate

        return current

    # --- schedule maintenance (E4-S5) -------------------------------------

    def open_occurrences(self, bill, today=None):
        """This bill's unsettled occurrences from today onward.

        Settled rows (SCHEDULED / PAID) and anything already in the past are
        excluded — a due date that has come and gone is history, whatever the
        user later edits.
        """
        today = today or timezone.localdate()

        return open_occurrences(
            bill.occurrences.filter(due_date__gte=today)
        )

    @transaction.atomic
    def rebuild_schedule(self, bill, today=None):
        """Drop the unsettled forward schedule and regenerate it.

        Used when ``frequency`` or ``anchor_date`` changes: the old due dates
        no longer follow from the rule, but settled ones must survive.
        """
        today = today or timezone.localdate()

        removed, _ = self.open_occurrences(bill, today).delete()
        created = self.generate_occurrences(bill, today=today)

        return removed, len(created)

    @transaction.atomic
    def reprice_open_occurrences(self, bill, today=None):
        """Push a new bill amount onto unsettled occurrences.

        FIXED bills only. A VARIABLE bill's amount is a per-cycle default that
        each occurrence may already have overridden, so it is left alone.
        """
        if bill.bill_type == BillType.VARIABLE:
            return 0

        return self.open_occurrences(bill, today).update(amount=bill.amount)

    @transaction.atomic
    def drop_open_occurrences(self, bill, today=None):
        """Remove the unsettled forward schedule, keeping settled history."""
        removed, _ = self.open_occurrences(bill, today).delete()

        return removed

    # --- reads ------------------------------------------------------------

    def get_upcoming_occurrences(self, user):
        return self.selector.get_upcoming_occurrences(user)

    def get_summary(self, user):
        return self.selector.get_summary(user)

    def get_next_due(self, user):
        return self.selector.get_next_due(user)

    # --- writes -----------------------------------------------------------

    def mark_as_paid(self, occurrence, payment_reference):
        if occurrence.status == BillOccurrenceStatus.PAID:
            raise ValidationError(
                {
                    "detail": "Bill is already paid."
                }
            )

        occurrence.status = BillOccurrenceStatus.PAID
        occurrence.paid_at = timezone.now()
        occurrence.payment_reference = payment_reference

        occurrence.save(
            update_fields=[
                "status",
                "paid_at",
                "payment_reference",
            ]
        )

        return occurrence
