"""Deterministic balance projection (E7-S3).

No LLM: projected balance = the funding account's current balance minus the
bills that come due on or before the target date (plus known recurring
inflows — none are detected today, so this is 0 for now). Purely arithmetic,
so it is exact to the cent and testable.
"""

from decimal import Decimal

from django.db.models import Sum
from django.utils import timezone

from apps.banking.models import BankAccount, BankConnectionStatus
from apps.bills.selectors.bill_occurrence_selector import BillOccurrenceSelector
from apps.common.exceptions import (
    NotFoundException,
    UnprocessableEntityException,
)


class ProjectionService:

    def __init__(self):
        self._occurrences = BillOccurrenceSelector()

    def project(self, *, user, account_id, target_date):
        today = timezone.localdate()

        if target_date < today:
            raise UnprocessableEntityException(
                "Projection date cannot be in the past."
            )

        account = (
            BankAccount.objects.filter(
                id=account_id,
                connection__user=user,
                connection__status=BankConnectionStatus.ACTIVE,
            )
            .first()
        )

        if account is None:
            # Covers both a foreign account and an unknown id — never reveal
            # which.
            raise NotFoundException("Funding account not found.")

        current_balance = account.available_balance or Decimal("0.00")

        outflow_total = (
            self._occurrences.get_upcoming_occurrences(user, today)
            .filter(due_date__lte=target_date)
            .aggregate(total=Sum("amount"))["total"]
            or Decimal("0.00")
        )

        # Recurring inflows: no inflow detection exists yet (E5 detects bills,
        # which are outflows), so this is 0 until that lands.
        inflow_total = Decimal("0.00")

        projected = current_balance - outflow_total + inflow_total

        return {
            "account_id": account.id,
            "date": target_date,
            "current_balance": current_balance,
            "outflow_total": outflow_total,
            "projected_balance": projected,
            "sufficient": projected >= Decimal("0.00"),
        }
