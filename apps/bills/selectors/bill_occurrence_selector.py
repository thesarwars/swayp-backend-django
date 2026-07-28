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
        return BillOccurrence.objects.filter(
            bill__user=user,
            bill__deleted_at__isnull=True,
        )

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

    def list_occurrences(self, user, filters=None, today=None):
        """Occurrence rows for the bills list screen (E4-S2).

        Filters: ``status`` (the computed one), ``vendor``, ``date_from``,
        ``date_to``. Status is filtered on the annotation, so "overdue" means
        what the screen shows rather than what happens to be stored.
        """
        today = today or timezone.localdate()
        filters = filters or {}

        queryset = annotate_status(self._for_user(user), today)

        vendor = (filters.get("vendor") or "").strip()
        if vendor:
            queryset = queryset.filter(bill__vendor_id=vendor)

        date_from = (filters.get("date_from") or "").strip()
        if date_from:
            queryset = queryset.filter(due_date__gte=date_from)

        date_to = (filters.get("date_to") or "").strip()
        if date_to:
            queryset = queryset.filter(due_date__lte=date_to)

        status = (filters.get("status") or "").strip().upper()
        if status in BillOccurrenceStatus.values:
            queryset = queryset.filter(computed_status=status)

        return queryset.select_related(*_RELATED).order_by("due_date")

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
