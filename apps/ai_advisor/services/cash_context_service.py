"""Flo cash-context advisor (E7-S2).

Every number is computed here in Python. The LLM only *phrases* the sentence
around those numbers, and only when the user has live consent and the
kill-switch (``FLO_LLM_ENABLED``) is on. Otherwise — and by default — a
deterministic template sentence is served, so the feature ships with no LLM
account. Any $-amount the LLM emits that isn't one of the computed figures
means it hallucinated, and we fall back to the template.
"""

import logging
import re
from decimal import Decimal

from django.conf import settings
from rest_framework.exceptions import ValidationError

from apps.ai_advisor.services.consent_service import ConsentService
from apps.banking.models import BankAccount, BankConnectionStatus
from apps.bills.selectors.bill_occurrence_selector import BillOccurrenceSelector
from integrations.factory import get_llm_provider

logger = logging.getLogger(__name__)

_MONEY = re.compile(r"\$\s?([\d,]+(?:\.\d{1,2})?)")

_SYSTEM = (
    "You are Flo, a concise cash-flow assistant. Rephrase the given figures "
    "into one friendly sentence. Never invent numbers; use only those given."
)


class CashContextService:

    def __init__(self):
        self._llm = get_llm_provider()
        self._occurrences = BillOccurrenceSelector()

    def build(self, *, user, amount, funding_account_id=None):
        account = self._funding_account(user, funding_account_id)
        figures = self._figures(user, amount, account)
        return {"text": self._phrase(user, figures), "figures": figures}

    # --- figures (Python only) -------------------------------------------

    def _funding_account(self, user, funding_account_id):
        queryset = BankAccount.objects.filter(
            connection__user=user,
            connection__status=BankConnectionStatus.ACTIVE,
        )

        if funding_account_id:
            account = queryset.filter(id=funding_account_id).first()
            if account is None:
                raise ValidationError(
                    {"funding_account_id": "Funding account not found."}
                )
            return account

        account = queryset.filter(is_default_funding_source=True).first()
        if account is None:
            raise ValidationError(
                {"funding_account_id": "No funding account is available."}
            )
        return account

    def _figures(self, user, amount, account):
        balance_now = account.available_balance or Decimal("0.00")

        upcoming = list(self._occurrences.get_upcoming_occurrences(user))
        upcoming_total = sum(
            (occ.amount for occ in upcoming), Decimal("0.00")
        )

        next_due = self._occurrences.get_next_due(user)
        next_bill = None
        if next_due is not None:
            next_bill = {
                "vendor": next_due.bill.vendor.name,
                "amount": next_due.amount,
                "due_date": next_due.due_date,
            }

        return {
            "balance_now": balance_now,
            "balance_after": balance_now - amount,
            "upcoming_count": len(upcoming),
            "upcoming_total": upcoming_total,
            "next_bill": next_bill,
        }

    # --- phrasing --------------------------------------------------------

    def _template(self, f):
        enough = "enough to cover" if f["balance_after"] >= f["upcoming_total"] else "short of"
        parts = [
            f"Balance ${f['balance_now']:,.2f}. After this payment you'll "
            f"have ${f['balance_after']:,.2f} — {enough} your "
            f"{f['upcoming_count']} upcoming bill(s) totaling "
            f"${f['upcoming_total']:,.2f}."
        ]
        nb = f["next_bill"]
        if nb:
            parts.append(
                f"Next up: {nb['vendor']} ${nb['amount']:,.2f} due "
                f"{nb['due_date']:%b %d}."
            )
        return " ".join(parts)

    def _phrase(self, user, figures):
        template = self._template(figures)

        if not getattr(settings, "FLO_LLM_ENABLED", False):
            return template

        if not ConsentService.has_live_consent(user):
            return template

        try:
            result = self._llm.complete(
                prompt=template, system=_SYSTEM, max_tokens=120
            )
            if self._numbers_safe(result.text, figures):
                return result.text.strip()
            logger.warning("Flo LLM emitted an unknown figure; using template")
        except Exception:  # noqa: BLE001 - advisor must never 500
            logger.warning("Flo LLM call failed; using template", exc_info=True)

        return template

    @staticmethod
    def _numbers_safe(text, figures):
        """No $-amount in the text may be one Flo did not compute."""
        known = {
            figures["balance_now"],
            figures["balance_after"],
            figures["upcoming_total"],
        }
        if figures["next_bill"]:
            known.add(figures["next_bill"]["amount"])

        for match in _MONEY.findall(text or ""):
            try:
                value = Decimal(match.replace(",", ""))
            except Exception:  # noqa: BLE001
                return False
            if value not in known:
                return False
        return True
