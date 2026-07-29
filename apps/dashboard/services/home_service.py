from apps.bills.selectors.bill_occurrence_selector import (
    BillOccurrenceSelector,
)
from apps.common.dates import today_eastern
from apps.common.enums import BillOccurrenceStatus
from apps.vendors.selectors.vendor_selector import VendorSelector

RECENT_BILLS_LIMIT = 5
VENDORS_PREVIEW_LIMIT = 3
PAY_PANEL_ITEM_LIMIT = 5

#: Priority order for the preloaded pay-panel tab.
TAB_ORDER = (
    BillOccurrenceStatus.OVERDUE,
    BillOccurrenceStatus.DUE,
    BillOccurrenceStatus.UPCOMING,
)


class HomeService:
    """The home aggregate (E8-S1) — composition only, no arithmetic.

    Every number on this screen has to reconcile with an endpoint another app
    owns, so each one comes from that app's selector rather than from a
    dashboard-local copy of the query.
    """

    def __init__(self):
        self.occurrences = BillOccurrenceSelector()

    def build(self, *, user, tab=None):
        today = today_eastern()

        summary = self.occurrences.get_summary(user, today)
        active_tab = self._resolve_tab(tab, summary)

        # Each queryset is materialised here rather than left to the
        # serializer, so the endpoint's query count is fixed and assertable.
        return {
            # First name, because the screen renders "Welcome Back, Jhon" —
            # the epic's greeting.name is "Jhon", not "Jhon Doe". Falls back to
            # the full name so a user who only filled in a surname is still
            # greeted by something. request.user is already loaded by
            # authentication; re-fetching it the way get_profile_summary does
            # would buy a 404 branch on the landing screen and nothing else.
            "greeting": {"name": user.first_name or user.get_full_name()},
            "stats": summary,
            "recent_bills": list(
                self.occurrences.get_recent_occurrences(
                    user, today, RECENT_BILLS_LIMIT
                )
            ),
            "vendors_preview": list(
                VendorSelector.preview(user, today, VENDORS_PREVIEW_LIMIT)
            ),
            "pay_panel": {
                "active_tab": active_tab.lower(),
                "tabs": summary,
                "items": list(
                    self.occurrences.list_occurrences(
                        user, {"status": active_tab}, today
                    )[:PAY_PANEL_ITEM_LIMIT]
                ),
            },
        }

    @staticmethod
    def _resolve_tab(tab, summary):
        """Explicit ?tab= wins; otherwise the first non-empty tab in order.

        docs/dashboard-plan.md:230 describes the right rail as "occurrence tab
        counts + top overdue", so OVERDUE is the default. Falling through to
        DUE then UPCOMING when overdue is empty costs no query — the counts are
        already in ``summary`` — and keeps the panel from landing empty for the
        user in good standing, who is the common case.
        """
        if tab:
            return tab.upper()

        counts = {
            BillOccurrenceStatus.OVERDUE: summary["overdue_count"],
            BillOccurrenceStatus.DUE: summary["due_count"],
            BillOccurrenceStatus.UPCOMING: summary["upcoming_count"],
        }

        for candidate in TAB_ORDER:
            if counts[candidate]:
                return candidate

        return BillOccurrenceStatus.OVERDUE
