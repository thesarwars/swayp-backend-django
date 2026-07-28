from datetime import date

from django.db.models import Prefetch, Sum
from django.db.models.functions import TruncMonth
from django.shortcuts import get_object_or_404
from django.utils import timezone

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

        status = (filters.get("status") or "").strip().upper()

        if status not in _VALID_STATUSES:
            status = VendorStatus.ACTIVE

        queryset = Vendor.objects.filter(user=user, status=status)

        search = (filters.get("search") or "").strip()
        if search:
            queryset = queryset.filter(name__icontains=search)

        category = (filters.get("category") or "").strip()
        if category:
            queryset = queryset.filter(category_id=category)

        rail = (filters.get("rail") or "").strip().upper()
        if rail in _VALID_RAILS:
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
                )
            )
            .distinct()
        )

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

        return total or 0

    @staticmethod
    def monthly_spend(vendor, months=12, today=None):
        """A dense 12-bucket monthly series for the spend bars (E3-S4).

        One query for the sums; the zero-filling is done in Python so months
        with no payments still appear rather than collapsing the chart.
        """
        today = today or timezone.localdate()

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
            row["month"].strftime("%Y-%m"): row["total"] or 0 for row in rows
        }

        series = []
        year, month = start.year, start.month

        for _ in range(months):
            key = f"{year:04d}-{month:02d}"
            series.append({"month": key, "total": by_month.get(key, 0)})
            month += 1
            if month > 12:
                month = 1
                year += 1

        return series

    @staticmethod
    def total_paid(vendor, months=12, today=None):
        """Sum of successful payments to this vendor over the window."""
        return sum(
            bucket["total"]
            for bucket in VendorSelector.monthly_spend(vendor, months, today)
        )

    @staticmethod
    def next_bill(vendor, today=None):
        """The vendor's nearest unsettled occurrence, or None."""
        from apps.bills.models.bill_occurrence import BillOccurrence
        from apps.bills.selectors.occurrence_status import open_occurrences

        today = today or timezone.localdate()

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
