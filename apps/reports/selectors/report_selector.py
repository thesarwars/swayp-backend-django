"""Payment reads behind the reports surface (E8-S2).

Query-time only: this app owns no tables and adds no columns. Every number a
report publishes is derived from ``apps.payments.models.Payment`` at request
time, so a report can never drift from the payment history it is meant to
reconcile against.
"""

import datetime as dt
from decimal import Decimal

from django.db.models import Count, Sum

from apps.common.dates import cutoff_datetime_et
from apps.common.enums import PaymentStatus
from apps.payments.models import Payment

#: Which payments a report is allowed to show at all.
#:
#: CANCELLED is absent on purpose. Cancellation is only permitted while the
#: cancellation deadline is still open (apps/payments/services/confirm_service
#: .py) and voids at the processor when one was already reached, so the money
#: provably never left the account; and the occurrence is handed straight back
#: to be paid again, so the replacement payment is the row that represents that
#: spend. Keeping the cancelled row would count the same bill twice.
REPORTABLE_STATUSES = (
    PaymentStatus.SCHEDULED,
    PaymentStatus.PENDING,
    PaymentStatus.PROCESSING,
    PaymentStatus.SUCCESSFUL,
    PaymentStatus.FAILED,
    PaymentStatus.REFUNDED,
    PaymentStatus.RETURNED,
)

#: Only money that actually reached a vendor belongs in a 1099.
PAID_STATUSES = (PaymentStatus.SUCCESSFUL,)

_ROW_RELATED = ("vendor", "bill_occurrence", "bill_occurrence__bill")
_MONEY_KEYS = ("amount", "fee", "total")
_ZERO = Decimal("0.00")


def _et_day_start(day):
    """Midnight Eastern on ``day``, as an aware datetime.

    Reuses the date engine's Eastern cutoff helper rather than a second
    definition of "start of day".
    """
    return cutoff_datetime_et(day, hour=0, minute=0)


def money_zeros():
    """An empty money bucket. Zeros, never nulls — a client renders a table
    without branching, and an empty report reads the same as a full one."""
    return {"count": 0, "amount": _ZERO, "fee": _ZERO, "total": _ZERO}


def add_money(into, bucket):
    """Fold one aggregate row into a bucket, coalescing null Sums.

    Returned so ``add_money(money_zeros(), row)`` is also the way a single
    aggregate row is coalesced. One definition of "add up money" for both the
    payments-report totals and the 1099 fold.
    """
    into["count"] += bucket["count"]

    for key in _MONEY_KEYS:
        into[key] += bucket[key] or _ZERO

    return into


class ReportSelector:

    @staticmethod
    def base_queryset(*, user, vendor_id=None, date_from=None, date_to=None):
        """The filtered set. Every number on the page comes from this one qs.

        Date bounds are applied to the raw ``created_at`` column as Eastern day
        boundaries rather than to a TruncDate annotation, so the range still
        uses Index(fields=["created_at"]) instead of forcing a scan over a
        computed expression.
        """
        queryset = Payment.objects.filter(
            user=user, status__in=REPORTABLE_STATUSES
        )

        if vendor_id:
            queryset = queryset.filter(vendor_id=vendor_id)

        if date_from:
            queryset = queryset.filter(created_at__gte=_et_day_start(date_from))

        if date_to:
            queryset = queryset.filter(
                created_at__lt=_et_day_start(date_to + dt.timedelta(days=1))
            )

        return queryset

    @staticmethod
    def rows(queryset):
        """The page's rows.

        select_related covers every column the row serializer touches, so a
        page is one query regardless of its size. ``transaction_reference``
        breaks ties because it is unique: without a total order, two rows
        sharing a ``created_at`` can repeat or vanish across page boundaries.
        """
        return queryset.select_related(*_ROW_RELATED).order_by(
            "-created_at", "-transaction_reference"
        )

    @staticmethod
    def totals(queryset):
        """Totals for the WHOLE filtered set — never for a page.

        Call this on the unsliced queryset, before PaginationService touches
        it: the paginator materialises ``list(result.object_list)``, so
        anything computed from its output is page-scoped by construction. The
        grand totals are folded from the buckets in Python rather than fetched
        by a second aggregate, so the block costs one query and the buckets are
        guaranteed to add up to it.
        """
        buckets = queryset.values("currency", "status").annotate(
            count=Count("id"),
            amount=Sum("amount"),
            fee=Sum("fee"),
            total=Sum("total"),
        )

        by_status = {}
        by_currency = {}
        grand = money_zeros()

        for bucket in buckets:
            add_money(
                by_status.setdefault(bucket["status"], money_zeros()), bucket
            )
            add_money(
                by_currency.setdefault(bucket["currency"], money_zeros()),
                bucket,
            )
            add_money(grand, bucket)

        return {
            **grand,
            # Null when the filtered set is empty or spans more than one
            # currency; by_currency is then the only honest breakdown.
            "currency": (
                next(iter(by_currency)) if len(by_currency) == 1 else None
            ),
            "by_status": by_status,
            "by_currency": [
                {"currency": code, **by_currency[code]}
                for code in sorted(by_currency)
            ],
        }

    @staticmethod
    def vendor_annual_totals(*, user, year):
        """Per-vendor SUCCESSFUL totals for an Eastern calendar year.

        No reporting threshold is applied: the IRS box mapping and the $600
        line are unspecified (PRD §10-Q4), and quietly dropping vendors under a
        guessed threshold would produce a tax artefact nobody can audit.
        """
        base = Payment.objects.filter(
            user=user,
            status__in=PAID_STATUSES,
            created_at__gte=_et_day_start(dt.date(year, 1, 1)),
            created_at__lt=_et_day_start(dt.date(year + 1, 1, 1)),
        )

        rows = (
            base.filter(vendor__isnull=False)
            .values("vendor_id", "vendor__name")
            .annotate(
                count=Count("id"),
                amount=Sum("amount"),
                fee=Sum("fee"),
                total=Sum("total"),
            )
            .order_by("-total", "vendor__name")
        )

        unattributed = base.filter(vendor__isnull=True).aggregate(
            count=Count("id"),
            amount=Sum("amount"),
            fee=Sum("fee"),
            total=Sum("total"),
        )

        return rows, unattributed
