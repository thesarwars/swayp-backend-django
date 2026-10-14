import uuid
from datetime import date
from decimal import Decimal

from django.db.models import (
    DecimalField,
    OuterRef,
    Prefetch,
    Q,
    Subquery,
    Sum,
    Value,
)
from django.db.models.functions import Coalesce, TruncMonth
from django.shortcuts import get_object_or_404
from rest_framework.exceptions import ValidationError

from apps.common.dates import today_eastern
from apps.common.enums import (
    PaymentStatus,
    VendorPaymentMethodType,
    VendorStatus,
)
from apps.payments.models import Payment
from apps.vendors.models import (
    Vendor,
    VendorPaymentMethod,
)

_VALID_STATUSES = {choice.value for choice in VendorStatus}
_VALID_RAILS = {choice.value for choice in VendorPaymentMethodType}


class VendorSelector:

    @staticmethod
    def list(user, filters=None):
        """Vendor rows for the list screen (E3-S2).

        Supports ``search`` (name contains), ``category``, ``rail`` (the
        vendor's primary payment method) and ``status``. Filtering lives here
        rather than in the view so list and summary share one definition.
        """
        filters = filters or {}

        # An unknown filter value is a 400, not a dropped filter: ?rail=BOGUS
        # used to answer every vendor, as if no filter had been sent (web B3).
        status = (filters.get("status") or "").strip().upper()

        if not status:
            status = VendorStatus.ACTIVE
        elif status not in _VALID_STATUSES:
            raise ValidationError(
                {"status": [f"Must be one of {', '.join(sorted(_VALID_STATUSES))}."]}
            )

        queryset = Vendor.objects.filter(user=user, status=status)

        search = (filters.get("search") or "").strip()
        if search:
            queryset = queryset.filter(name__icontains=search)

        category = (filters.get("category") or "").strip()
        if category:
            try:
                queryset = queryset.filter(category_id=uuid.UUID(category))
            except ValueError:
                raise ValidationError({"category": ["Must be a category id."]})

        rail = (filters.get("rail") or "").strip().upper()
        if rail and rail not in _VALID_RAILS:
            raise ValidationError(
                {"rail": [f"Must be one of {', '.join(sorted(_VALID_RAILS))}."]}
            )
        if rail:
            # Both conditions must hold on the *same* payment method, so they
            # stay inside one filter() call.
            queryset = queryset.filter(
                payment_methods__is_primary=True,
                payment_methods__method_type=rail,
            )

        return (
            queryset.select_related("category")
            .prefetch_related(
                Prefetch(
                    "payment_methods",
                    queryset=VendorPaymentMethod.objects.filter(
                        is_primary=True
                    ),
                    # Named, so the serializer reads this list directly. A
                    # plain ``obj.payment_methods.filter(...)`` would ignore
                    # the prefetch and re-query per row — the prefetch was
                    # here all along and the serializer was throwing it away.
                    to_attr="primary_methods",
                )
            )
            .annotate(**VendorSelector.next_bill_annotations())
            .distinct()
        )

    @staticmethod
    def next_bill_annotations(today=None):
        """Subqueries for the vendor's nearest unsettled occurrence.

        Three annotations rather than a per-row lookup: the list screen shows
        next due date, amount and frequency for every vendor, and fetching
        them one vendor at a time cost three queries each. Subqueries keep the
        whole page at a fixed cost however many vendors it holds.
        """
        from apps.bills.models.bill_occurrence import BillOccurrence
        from apps.bills.selectors.occurrence_status import open_occurrences

        # Eastern for the same reason next_bill() is: a UTC "today" drops an
        # occurrence due today out of next_due for five hours each evening.
        today = today or today_eastern()

        base = open_occurrences(
            BillOccurrence.objects.filter(
                bill__vendor=OuterRef("pk"),
                bill__deleted_at__isnull=True,
                due_date__gte=today,
            )
        ).order_by("due_date")

        return {
            "next_due_date": Subquery(base.values("due_date")[:1]),
            # output_field is not decoration: without it the scale is lost and
            # $777.00 serialises as "777". Money is a 2dp string everywhere
            # else in the API and a client parsing it would not notice the
            # difference until a cent went missing.
            "next_amount": Subquery(
                base.values("amount")[:1],
                output_field=DecimalField(max_digits=18, decimal_places=2),
            ),
            "next_frequency": Subquery(base.values("bill__frequency")[:1]),
        }

    @staticmethod
    def detail(user, vendor_id):
        return get_object_or_404(
            Vendor.objects.select_related("category").prefetch_related(
                "payment_methods"
            ),
            id=vendor_id,
            user=user,
            status=VendorStatus.ACTIVE,
        )

    @staticmethod
    def summary(user, filters=None):
        """Counts over the same rows the list returns under ``filters``."""
        vendors = VendorSelector.list(user, filters)

        return {
            "total": vendors.count(),
            "network": vendors.filter(
                payment_methods__method_type=VendorPaymentMethodType.NETWORK
            ).distinct().count(),
            "ach": vendors.filter(
                payment_methods__method_type=VendorPaymentMethodType.ACH
            ).distinct().count(),
            "check": vendors.filter(
                payment_methods__method_type=VendorPaymentMethodType.CHECK
            ).distinct().count(),
            # Recurring value routed over check: the per-cycle amount of
            # every bill whose selected method is CHECK (E3-S2).
            "check_total": VendorSelector.check_total(vendors),
        }

    @staticmethod
    def preview(user, today=None, limit=3):
        """Top vendors for the home dashboard, ranked by this month's value.

        Built on ``VendorSelector.list(user)`` with no filters so the rowset is
        provably the one vendors/summary/ counts — list() defaults status to
        ACTIVE and summary() is literally list().count().
        """
        today = today or today_eastern()

        return (
            VendorSelector.list(user)
            # list() attaches a primary-method Prefetch that would cost a
            # second query for data the `rail` Subquery already supplies.
            .prefetch_related(None)
            .annotate(
                monthly_amount=Coalesce(
                    Sum(
                        "bills__occurrences__amount",
                        filter=Q(
                            # bills__user as well as the vendor's own user:
                            # nothing in the schema forces bill.user to equal
                            # bill.vendor.user, so without it a bill someone
                            # else owns against this vendor would be summed
                            # into this user's card. Every sibling selector
                            # scopes by the bill's owner; so does this one.
                            bills__user=user,
                            bills__deleted_at__isnull=True,
                            bills__occurrences__due_date__year=today.year,
                            bills__occurrences__due_date__month=today.month,
                        ),
                    ),
                    Value(Decimal("0.00")),
                    output_field=DecimalField(
                        max_digits=18, decimal_places=2
                    ),
                ),
                # The primary method's rail, same answer as
                # VendorListSerializer.get_payment_rail. [:1] is exact rather
                # than arbitrary: one_primary_method_per_vendor guarantees it.
                rail=Subquery(
                    VendorPaymentMethod.objects.filter(
                        vendor=OuterRef("pk"), is_primary=True
                    ).values("method_type")[:1]
                ),
            )
            # Highest value first — that is what "top vendors" means on the
            # home screen. Name breaks ties so the preview is stable across
            # requests rather than following whatever order the DB returns.
            .order_by("-monthly_amount", "name")[:limit]
        )

    @staticmethod
    def payment_methods(user, vendor_id):
        return (
            VendorPaymentMethod.objects.filter(
                vendor__id=vendor_id,
                vendor__user=user,
                vendor__status=VendorStatus.ACTIVE,
            )
            .order_by("-is_primary", "method_type")
        )


    @staticmethod
    def check_total(vendors):
        """Summed per-cycle amount of bills paid by check for these vendors."""
        from apps.bills.models.bill import Bill

        total = Bill.objects.filter(
            vendor__in=vendors,
            deleted_at__isnull=True,
            payment_method__method_type=VendorPaymentMethodType.CHECK,
        ).aggregate(total=Sum("amount"))["total"]

        return total or Decimal("0.00")

    @staticmethod
    def monthly_spend(vendor, months=12, today=None):
        """A dense 12-bucket monthly series for the spend bars (E3-S4).

        One query for the sums; the zero-filling is done in Python so months
        with no payments still appear rather than collapsing the chart.
        """
        # Eastern, not localdate() — the whole vendor screen has to agree on
        # which day it is, and ``preview``/``recent_occurrences`` are Eastern.
        today = today or today_eastern()

        start_year, start_month = today.year, today.month
        offset = months - 1
        start_month -= offset
        while start_month <= 0:
            start_month += 12
            start_year -= 1

        start = date(start_year, start_month, 1)

        rows = (
            Payment.objects.filter(
                bill_occurrence__bill__vendor=vendor,
                status=PaymentStatus.SUCCESSFUL,
                created_at__date__gte=start,
            )
            .annotate(month=TruncMonth("created_at"))
            .values("month")
            .annotate(total=Sum("total"))
        )

        by_month = {
            row["month"].strftime("%Y-%m"): row["total"] or Decimal("0.00")
            for row in rows
        }

        series = []
        year, month = start.year, start.month

        for _ in range(months):
            key = f"{year:04d}-{month:02d}"
            # Decimal for every bucket, including empty ones — mixing int 0
            # with Decimal totals makes the series awkward to consume.
            series.append(
                {
                    "month": key,
                    "total": by_month.get(key, Decimal("0.00")),
                }
            )
            month += 1
            if month > 12:
                month = 1
                year += 1

        return series

    @staticmethod
    def total_paid(vendor, months=12, today=None):
        """Sum of successful payments to this vendor over the window."""
        return sum(
            (
                bucket["total"]
                for bucket in VendorSelector.monthly_spend(
                    vendor, months, today
                )
            ),
            Decimal("0.00"),
        )

    @staticmethod
    def recent_occurrences(vendor, limit=5):
        """The vendor's bills as occurrences with a read-time status chip.

        Powers the embedded bills list on the vendor detail (829:3866) —
        nearest due first, computed status (Overdue/Due/Upcoming/Paid…).
        """
        from apps.bills.models.bill_occurrence import BillOccurrence
        from apps.bills.selectors.occurrence_status import annotate_status

        queryset = annotate_status(
            BillOccurrence.objects.filter(
                bill__vendor=vendor,
                bill__deleted_at__isnull=True,
            ).select_related("bill", "bill__category")
        ).order_by("due_date")

        return list(queryset[:limit])

    @staticmethod
    def next_bill(vendor, today=None):
        """The vendor's nearest unsettled occurrence, or None."""
        from apps.bills.models.bill_occurrence import BillOccurrence
        from apps.bills.selectors.occurrence_status import open_occurrences

        # Eastern: ``recent_occurrences`` labels an occurrence due today "DUE"
        # off annotate_status()'s Eastern default, so a UTC ``today`` here
        # would drop that same row out of next_due for five hours an evening.
        today = today or today_eastern()

        return (
            open_occurrences(
                BillOccurrence.objects.filter(
                    bill__vendor=vendor,
                    bill__deleted_at__isnull=True,
                    due_date__gte=today,
                )
            )
            .select_related("bill")
            .order_by("due_date")
            .first()
        )
