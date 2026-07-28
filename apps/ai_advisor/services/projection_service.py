"""Deterministic balance projection (E7-S3).

No LLM. The projected balance is:

    current balance
      - bills that come due on or before the target date
      - money already committed out of this account but not yet settled
      + known recurring inflows (none are detected today, so 0)

Three things this deliberately does *not* do the obvious way:

* **Bills come from the recurrence rule, not just from materialised rows.**
  E4 only keeps two cycles of ``BillOccurrence`` pre-created, which is ~13 days
  for a weekly bill. Summing rows alone therefore returns *zero* outflow past
  that horizon and reports a comfortable surplus — silently, and more wrongly
  the further out you ask. ``due_dates_through`` walks the rule instead, and a
  materialised row wins over the rule's default amount wherever one exists.

* **In-flight payments are subtracted.** An occurrence flips to SCHEDULED the
  moment a ``Payment`` row is created, before anything executes, which drops it
  out of the "unpaid bills" query — while the money has not left the account
  either. Counting live ``Payment`` rows closes that window, and also catches
  the ad-hoc payments that have no occurrence at all.

* **The balance is refreshed first.** It is otherwise a link-time snapshot.

Purely arithmetic, so it is exact to the cent and testable.
"""

from decimal import Decimal

from django.db.models import Q
from django.utils import timezone

from apps.banking.models import BankAccount, BankConnectionStatus
from apps.banking.services.balance_service import BalanceService
from apps.bills.models.bill import Bill
from apps.bills.models.bill_occurrence import BillOccurrence
from apps.bills.services.bill_occurrence_service import BillOccurrenceService
from apps.common.enums import BillOccurrenceStatus, PaymentStatus
from apps.common.exceptions import (
    NotFoundException,
    UnprocessableEntityException,
)
from apps.payments.models import Payment

#: Money committed out of the account but not yet settled. RETURNED/FAILED/
#: CANCELLED money came back (or never left); SUCCESSFUL money is already
#: reflected in the balance the bank reports.
LIVE_PAYMENT_STATUSES = (
    PaymentStatus.SCHEDULED,
    PaymentStatus.PENDING,
    PaymentStatus.PROCESSING,
)


class ProjectionService:

    def __init__(self):
        self._schedule = BillOccurrenceService()
        self._balances = BalanceService()

    def project(self, *, user, account_id, target_date):
        today = timezone.localdate()

        if target_date < today:
            raise UnprocessableEntityException(
                "Projection date cannot be in the past."
            )

        account = BankAccount.objects.filter(
            id=account_id,
            connection__user=user,
            connection__status=BankConnectionStatus.ACTIVE,
        ).select_related("connection").first()

        if account is None:
            # Covers both a foreign account and an unknown id — never reveal
            # which.
            raise NotFoundException("Funding account not found.")

        self._balances.refresh(account)

        current_balance = account.available_balance or Decimal("0.00")

        committed_total, committed_occurrence_ids = self._committed(
            user=user, account=account, target_date=target_date
        )

        outflow_total = self._outflow(
            user=user,
            today=today,
            target_date=target_date,
            skip_occurrence_ids=committed_occurrence_ids,
        )

        # Recurring inflows: no inflow detection exists yet (E5 detects bills,
        # which are outflows), so this is 0 until that lands.
        inflow_total = Decimal("0.00")

        projected = (
            current_balance - outflow_total - committed_total + inflow_total
        )

        return {
            "account_id": account.id,
            "date": target_date,
            "current_balance": current_balance,
            "balance_as_of": account.balance_as_of,
            "outflow_total": outflow_total,
            "committed_total": committed_total,
            "projected_balance": projected,
            "sufficient": projected >= Decimal("0.00"),
        }

    # --- terms ------------------------------------------------------------

    def _committed(self, *, user, account, target_date):
        """Money already on its way out of this account.

        ``scheduled_for`` NULL means "send now", so it is in flight regardless
        of the target date. Returns the occurrence ids these payments settle so
        the bill term can skip them rather than count the same money twice.
        """
        payments = (
            Payment.objects.filter(
                user=user,
                funding_account=account,
                status__in=LIVE_PAYMENT_STATUSES,
            )
            .filter(
                Q(scheduled_for__isnull=True)
                | Q(scheduled_for__lte=target_date)
            )
            .values_list("total", "bill_occurrence_id")
        )

        total = Decimal("0.00")
        occurrence_ids = set()

        for payment_total, occurrence_id in payments:
            total += payment_total

            if occurrence_id is not None:
                occurrence_ids.add(occurrence_id)

        return total, occurrence_ids

    def _outflow(self, *, user, today, target_date, skip_occurrence_ids):
        """Bills coming due in ``[today, target_date]`` that are still owed."""
        bills = list(
            Bill.objects.filter(user=user, deleted_at__isnull=True)
        )

        if not bills:
            return Decimal("0.00")

        rows = BillOccurrence.objects.filter(
            bill__in=bills,
            due_date__gte=today,
            due_date__lte=target_date,
        )

        materialised = {(row.bill_id, row.due_date): row for row in rows}

        total = Decimal("0.00")

        for bill in bills:
            due_dates = set(
                self._schedule.due_dates_through(bill, target_date, today)
            )

            # A rebuilt schedule keeps settled rows on dates the current rule
            # no longer produces, so rows are unioned in rather than assumed
            # to be a subset of the rule.
            due_dates |= {
                due_date
                for (bill_id, due_date) in materialised
                if bill_id == bill.id
            }

            for due_date in sorted(due_dates):
                occurrence = materialised.get((bill.id, due_date))

                if occurrence is None:
                    # Past E4's horizon: the row does not exist yet, so the
                    # rule's amount is the best available figure.
                    total += bill.amount
                    continue

                if occurrence.id in skip_occurrence_ids:
                    # A live payment already covers it; counted as committed.
                    continue

                if occurrence.status == BillOccurrenceStatus.PAID:
                    continue

                total += occurrence.amount

        return total
