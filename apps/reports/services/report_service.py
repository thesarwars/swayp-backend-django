from apps.common.dates import today_eastern
from apps.common.enums import PlanCode
from apps.common.exceptions import ForbiddenException, NotFoundException
from apps.common.pagination import PaginationService
from apps.common.plans import has_plan_at_least
from apps.reports.selectors.report_selector import (
    ReportSelector,
    add_money,
    money_zeros,
)
from apps.vendors.models import Vendor

#: Written once, raised twice — the view raises it to fix the order of the 403
#: against the 405, the service to protect non-HTTP callers.
PLAN_GATE_MESSAGE = (
    "1099 reporting is available on the Standard plan and above. "
    "Upgrade your plan to run this report."
)


class ReportService:
    """Composition only — the arithmetic lives in ReportSelector (E8-S2)."""

    def payments_report(
        self,
        *,
        user,
        vendor_id=None,
        date_from=None,
        date_to=None,
        page=1,
        page_size=20,
    ):
        vendor = self._vendor(user=user, vendor_id=vendor_id)

        queryset = ReportSelector.base_queryset(
            user=user,
            vendor_id=vendor.id if vendor else None,
            date_from=date_from,
            date_to=date_to,
        )

        # Totals FIRST, from the unsliced queryset. Order is load-bearing:
        # PaginationService.paginate materialises the page, and the AC is that
        # totals describe the whole filtered set.
        totals = ReportSelector.totals(queryset)

        page_result = PaginationService.paginate(
            queryset=ReportSelector.rows(queryset),
            page=page,
            page_size=page_size,
        )

        return {
            "rows": page_result["items"],
            "totals": totals,
            "filters": {
                "vendor": vendor.id if vendor else None,
                "date_from": date_from,
                "date_to": date_to,
            },
            "pagination": page_result["pagination"],
        }

    @staticmethod
    def _vendor(*, user, vendor_id):
        """Resolve and own-check the vendor filter.

        One 404 for both "no such vendor" and "someone else's vendor": a report
        has no reason to tell a caller which vendor ids exist. This deliberately
        does not copy the 422/404 split in ProjectionService._account — that
        split exists because E7-S3 AC2 asks for it, and no report AC does.
        """
        if not vendor_id:
            return None

        vendor = Vendor.objects.filter(id=vendor_id, user=user).first()

        if vendor is None:
            raise NotFoundException("Vendor not found.")

        return vendor

    def vendor_1099(self, *, user, year=None):
        """Per-vendor annual totals, Standard plan and above (BRD §6.2).

        The gate lives here as well as in the view: the view's copy fixes the
        ORDER of the 403 against the 405, this one is the authority for any
        caller that is not an HTTP request (a task, a shell, a future export).
        """
        if not has_plan_at_least(user, PlanCode.STANDARD):
            raise ForbiddenException(PLAN_GATE_MESSAGE)

        year = year or today_eastern().year

        vendor_rows, unattributed_row = ReportSelector.vendor_annual_totals(
            user=user, year=year
        )

        rows = []
        totals = money_zeros()

        for row in vendor_rows:
            rows.append(
                {
                    "vendor_id": row["vendor_id"],
                    "vendor_name": row["vendor__name"],
                    **add_money(money_zeros(), row),
                }
            )
            add_money(totals, row)

        # Successful payments with no vendor FK, folded into the same totals so
        # rows + unattributed reconcile exactly. A tax dataset that silently
        # loses money is worse than one that admits it.
        unattributed = add_money(money_zeros(), unattributed_row)
        add_money(totals, unattributed)

        return {
            "year": year,
            "rows": rows,
            "totals": totals,
            "unattributed": unattributed,
        }
