from apps.bills.selectors.bill_occurrence_selector import (
    BillOccurrenceSelector,
)
from apps.common.dates import today_eastern
from apps.common.enums import BillOccurrenceStatus
from apps.notifications.selectors.notification_selector import (
    NotificationSelector,
)
from apps.vendors.selectors.vendor_selector import VendorSelector
from apps.users.services.display_name import first_name

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

    @staticmethod
    def _greeting_name(person):
        # One explicit read, so the home query budget does not depend on
        # whether this request already cached person.profile.
        from apps.users.models import Profile

        profile = Profile.objects.filter(user=person).first() or False

        return first_name(person, profile)

    def build(self, *, user, tab=None, viewer=None):
        """``user`` is the account whose bills are shown; ``viewer`` is the
        person signed in. They differ for a team member, and notifications
        belong to the person, so the unread count is the viewer's — the same
        number dashboard/profile-summary reports."""
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
            # The viewer, not the account: a teammate is greeted by their own
            # name (web B4), from the same source as every other screen.
            "greeting": {"name": self._greeting_name(viewer or user)},
            # The home bell (DASH-4), so the screen needs no second request.
            "unread_notification_count": NotificationSelector().unread_count(
                user=viewer or user
            ),
            "funding_account": self._funding_account(user),
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
    def _funding_account(user):
        """The account a payment would debit, for the "From" row (DASH-9).

        The same rule PaymentCreateService applies when no account is named:
        the default funding source on an ACTIVE connection. None is exactly
        the case where creating a payment is refused, so the screen can say
        "connect a bank" before the user tries to pay.
        """
        from apps.banking.models import BankAccount, BankConnectionStatus

        account = BankAccount.objects.filter(
            connection__user=user,
            connection__status=BankConnectionStatus.ACTIVE,
            is_default_funding_source=True,
        ).first()

        if account is None:
            return None

        return {
            "id": account.id,
            "name": account.name,
            "mask": account.mask,
            "display": account.masked_name,
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
