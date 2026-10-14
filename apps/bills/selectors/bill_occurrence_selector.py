import uuid
from decimal import Decimal

from django.db.models import Count, Q
from django.db.models.aggregates import Sum
from rest_framework.exceptions import ValidationError

from apps.bills.models.bill_occurrence import BillOccurrence
from apps.bills.selectors.bill_selector import BillSelector
from apps.bills.selectors.occurrence_status import (
    TERMINAL_STATUSES,
    annotate_row,
    annotate_status,
    open_occurrences,
)
from apps.common.dates import today_eastern
from apps.common.enums import BillOccurrenceStatus

_RELATED = (
    "bill",
    "bill__vendor",
    "bill__category",
    "bill__payment_method",
)


#: ?ordering= values (web §4). due_date, earliest first, stays the default.
ORDERINGS = {
    "due_date": ("due_date",),
    "-due_date": ("-due_date",),
    "amount": ("amount", "due_date"),
    "-amount": ("-amount", "due_date"),
    "vendor": ("bill__vendor__name", "due_date"),
    "-vendor": ("-bill__vendor__name", "due_date"),
}


def _uuid(value, field):
    try:
        return uuid.UUID(value)
    except ValueError:
        raise ValidationError({field: [f"Must be a {field} id."]})


def _date(filters, key):
    """A YYYY-MM-DD filter, or None; a malformed one is a 400, not a 500."""
    import datetime as dt

    raw = (filters.get(key) or "").strip()

    if not raw:
        return None

    try:
        return dt.date.fromisoformat(raw)
    except ValueError:
        raise ValidationError({key: ["Use YYYY-MM-DD."]})


def _multi(filters, key):
    """Every value of ``key``: repeated params, comma-separated, or both."""
    if hasattr(filters, "getlist"):
        raw = filters.getlist(key)
    else:
        raw = [filters.get(key) or ""]

    return [
        part.strip()
        for value in raw
        for part in str(value).split(",")
        if part.strip()
    ]


class BillOccurrenceSelector:

    def _for_user(self, user):
        return BillOccurrence.objects.filter(
            bill__user=user,
            bill__deleted_at__isnull=True,
        )

    def get_upcoming_occurrences(self, user, today=None):
        today = today or today_eastern()

        queryset = open_occurrences(
            self._for_user(user).filter(due_date__gte=today)
        )

        return (
            annotate_status(queryset, today)
            .select_related(*_RELATED)
            .order_by("due_date")
        )

    def get_summary(self, user, today=None):
        """The numbers behind bills/summary/ and the dashboard stat cards.

        One conditional aggregate rather than a Sum plus three counts: every
        predicate is on a local column of ``bill_occurrences`` after the single
        join to ``bills``, and the dashboard reads all five at once. The three
        count predicates are term-for-term the ``When()`` branches of
        ``status_expression``, which is what makes the tab counts and the rows
        behind them provably describe the same occurrences.
        """
        today = today or today_eastern()

        # Same rows as open_occurrences(): status is non-nullable, so the
        # negated IN and the .exclude() agree on NULL semantics.
        open_q = ~Q(status__in=TERMINAL_STATUSES)
        month_q = Q(due_date__year=today.year, due_date__month=today.month)

        agg = self._for_user(user).aggregate(
            total=Sum("amount", filter=open_q & month_q),
            paid_count=Count(
                "id", filter=month_q & Q(status=BillOccurrenceStatus.PAID)
            ),
            upcoming_count=Count("id", filter=open_q & Q(due_date__gt=today)),
            due_count=Count("id", filter=open_q & Q(due_date=today)),
            overdue_count=Count("id", filter=open_q & Q(due_date__lt=today)),
            # Any month: everything queued to pay, for the "Scheduled" chip
            # (BILLS-8). Same aggregate, so no extra query.
            scheduled_count=Count(
                "id", filter=Q(status=BillOccurrenceStatus.SCHEDULED)
            ),
        )

        return {
            # "Due this month" is what the user still owes, so settled
            # occurrences drop out of the total.
            # Decimal, not int 0 — this figure is also read raw by the
            # onboarding summary, which has no serializer to coerce it, so an
            # empty month would otherwise render as 0 there and "0.00" here.
            "total_due_this_month": agg["total"] or Decimal("0.00"),

            "upcoming_count": agg["upcoming_count"],
            "due_count": agg["due_count"],
            "overdue_count": agg["overdue_count"],
            "paid_count": agg["paid_count"],
            "scheduled_count": agg["scheduled_count"],
            # Bills, not occurrences — "Overdue 14 / Due 9 / Upcoming 14" and
            # "Total Bills 6" only reconcile if they count different units
            # (docs/epics/epic-4-bills.md:7).
            "total_bills": BillSelector().count_active_bills(user),
        }

    def get_recent_occurrences(self, user, today=None, limit=5):
        """The most recently due occurrences, settled ones included (E8-S1).

        Every status, not just the open ones: the PAID/SCHEDULED chips are the
        only place the dashboard shows that something went right, and the
        forward-looking list is already the pay panel. ``annotate_status`` is
        load-bearing here — ``BillOccurrenceRowSerializer.get_status`` falls
        back to the stored status, which defaults to UPCOMING, so an
        unannotated overdue row would render "UPCOMING".
        """
        today = today or today_eastern()

        return (
            annotate_row(
                self._for_user(user).filter(due_date__lte=today), today
            )
            .select_related(*_RELATED)
            .order_by("-due_date", "-created_at")[:limit]
        )

    def list_occurrences(self, user, filters=None, today=None):
        """Occurrence rows for the bills list screen (E4-S2).

        Filters: ``status`` (the computed one; several allowed), ``vendor``,
        ``category`` (several allowed), ``date_from``, ``date_to``. Status is
        filtered on the annotation, so "overdue" means what the screen shows
        rather than what happens to be stored.
        """
        today = today or today_eastern()
        filters = filters or {}

        queryset = annotate_row(self._for_user(user), today)

        vendor = (filters.get("vendor") or "").strip()
        if vendor:
            queryset = queryset.filter(bill__vendor_id=_uuid(vendor, "vendor"))

        # One bill's due dates, for the bill page's history (web §4).
        bill = (filters.get("bill") or "").strip()
        if bill:
            queryset = queryset.filter(bill_id=_uuid(bill, "bill"))

        # Vendor name or bill notes contain it, case-insensitive (web §4).
        search = (filters.get("search") or "").strip()
        if search:
            queryset = queryset.filter(
                Q(bill__vendor__name__icontains=search)
                | Q(bill__notes__icontains=search)
            )

        date_from = _date(filters, "date_from")
        if date_from:
            queryset = queryset.filter(due_date__gte=date_from)

        date_to = _date(filters, "date_to")
        if date_to:
            queryset = queryset.filter(due_date__lte=date_to)

        # Repeatable or comma-separated: ?status=OVERDUE&status=DUE or
        # ?status=OVERDUE,DUE (BILLS-8). An unknown value is a 400; it used to
        # be dropped, so ?status=BOGUS listed everything (web B3).
        statuses = [value.upper() for value in _multi(filters, "status")]
        unknown = [s for s in statuses if s not in BillOccurrenceStatus.values]
        if unknown:
            raise ValidationError({"status": [
                "Must be one of "
                + ", ".join(BillOccurrenceStatus.values) + "."
            ]})
        if statuses:
            queryset = queryset.filter(computed_status__in=statuses)

        # Category ids, repeatable or comma-separated (BILLS-14).
        categories = _multi(filters, "category")
        if categories:
            try:
                queryset = queryset.filter(
                    bill__category_id__in=[uuid.UUID(c) for c in categories]
                )
            except ValueError:
                raise ValidationError(
                    {"category": ["Must be category ids."]}
                )

        ordering = (filters.get("ordering") or "due_date").strip()
        if ordering not in ORDERINGS:
            raise ValidationError({"ordering": [
                "Must be one of " + ", ".join(ORDERINGS) + "."
            ]})

        return queryset.select_related(*_RELATED).order_by(
            *ORDERINGS[ordering], "id"
        )

    def get_occurrence(self, user, occurrence_id, today=None):
        """One row, the same shape as the list, or None (PAY-4)."""
        return (
            annotate_row(self._for_user(user), today or today_eastern())
            .select_related(*_RELATED)
            .filter(id=occurrence_id)
            .first()
        )

    def get_next_due(self, user, today=None):
        """Nearest unsettled occurrence (E4-S8 — excludes SCHEDULED/PAID)."""
        today = today or today_eastern()

        queryset = open_occurrences(
            self._for_user(user).filter(due_date__gte=today)
        )

        return (
            annotate_status(queryset, today)
            .select_related(*_RELATED)
            .order_by("due_date")
            .first()
        )
