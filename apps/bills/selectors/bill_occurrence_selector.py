from django.db.models.aggregates import Sum
from django.utils import timezone

from apps.bills.models.bill_occurrence import BillOccurrence
from apps.bills.selectors.occurrence_status import (
    annotate_status,
    open_occurrences,
)
from apps.common.enums import BillOccurrenceStatus

_RELATED = (
    "bill",
    "bill__vendor",
    "bill__category",
)


class BillOccurrenceSelector:

    def _for_user(self, user):
        return BillOccurrence.objects.filter(bill__user=user)

    def get_upcoming_occurrences(self, user, today=None):
        today = today or timezone.localdate()

        queryset = open_occurrences(
            self._for_user(user).filter(due_date__gte=today)
        )

        return (
            annotate_status(queryset, today)
            .select_related(*_RELATED)
            .order_by("due_date")
        )

    def get_summary(self, user, today=None):
        today = today or timezone.localdate()

        unpaid = open_occurrences(self._for_user(user))

        return {
            # "Due this month" is what the user still owes, so settled
            # occurrences drop out of the total.
            "total_due_this_month": unpaid.filter(
                due_date__year=today.year,
                due_date__month=today.month,
            ).aggregate(
                total=Sum("amount")
            )["total"] or 0,

            "upcoming_count": unpaid.filter(due_date__gt=today).count(),
            "due_count": unpaid.filter(due_date=today).count(),
            "overdue_count": unpaid.filter(due_date__lt=today).count(),
        }

    def get_next_due(self, user, today=None):
        """Nearest unsettled occurrence (E4-S8 — excludes SCHEDULED/PAID)."""
        today = today or timezone.localdate()

        queryset = open_occurrences(
            self._for_user(user).filter(due_date__gte=today)
        )

        return (
            annotate_status(queryset, today)
            .select_related(*_RELATED)
            .order_by("due_date")
            .first()
        )
