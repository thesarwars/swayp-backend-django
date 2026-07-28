"""Flo cash-context advisor (E7-S2).

Every number is computed here in Python. The LLM only *phrases* the sentence
around those numbers, and only when the user has live consent and the
kill-switch (``FLO_LLM_ENABLED``) is on. Otherwise — and by default — a
deterministic template sentence is served, so the feature ships with no LLM
account.

The phrasing is only allowed through if it says the same numbers the template
says: same values, same count, same signs, nothing added, nothing dropped
(``_numeric_fingerprint``). Set-membership is not enough — checking only that
each figure is "one of ours" lets the model swap two of them, and the swap that
matters is the one between a balance and a shortfall. Falling back to the
template is cheap and is the designed default, so the check errs strict.
"""

import logging
import re
from decimal import Decimal, InvalidOperation

from django.conf import settings
from django.core.cache import cache
from django.utils import timezone
from rest_framework.exceptions import ValidationError

from apps.ai_advisor.services.consent_service import ConsentService
from apps.banking.models import BankAccount, BankConnectionStatus
from apps.banking.services.balance_service import BalanceService
from apps.bills.selectors.bill_occurrence_selector import BillOccurrenceSelector
from integrations.factory import get_llm_provider

logger = logging.getLogger(__name__)

#: Any numeral, with the sign attached however it is written. `$-1,000.00` and
#: `-$1,000.00` both mean minus a thousand; a regex anchored on `$` sees
#: neither sign and reads both as +1000, which is exactly the confusion between
#: "you have $1,000" and "you are $1,000 overdrawn" that this guard exists to
#: catch. A trailing `%` is kept distinct so a hallucinated percentage cannot
#: pass as a matching amount.
_NUMBER = re.compile(
    r"""
    (?P<neg_outer>-)?\s*
    \$?\s*
    (?P<neg_inner>-)?
    (?P<digits>\d[\d,]*(?:\.\d+)?)
    \s*
    (?P<percent>%)?
    """,
    re.VERBOSE,
)

_SYSTEM = (
    "You are Flo, a concise cash-flow assistant. Rephrase the given sentence "
    "as one friendly sentence. Use every number exactly as it is written, "
    "mention each one exactly once, and never introduce a number that is not "
    "already there."
)


class CashContextService:

    def __init__(self):
        self._llm = get_llm_provider()
        self._occurrences = BillOccurrenceSelector()
        self._balances = BalanceService()

    def build(self, *, user, amount, funding_account_id=None):
        account = self._funding_account(user, funding_account_id)

        # The stored balance is written at link time and would otherwise be
        # quoted as fact however old it is.
        self._balances.refresh(account)

        figures = self._figures(user, amount, account)

        return {"text": self._phrase(user, figures), "figures": figures}

    # --- figures (Python only) -------------------------------------------

    def _funding_account(self, user, funding_account_id):
        queryset = BankAccount.objects.filter(
            connection__user=user,
            connection__status=BankConnectionStatus.ACTIVE,
        ).select_related("connection")

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
            "balance_as_of": account.balance_as_of,
            "upcoming_count": len(upcoming),
            "upcoming_total": upcoming_total,
            "next_bill": next_bill,
        }

    # --- phrasing --------------------------------------------------------

    #: Vendor names are user-supplied and land in a sentence spoken in Flo's
    #: voice, so they get trimmed to something that reads as a name.
    VENDOR_DISPLAY_MAX = 40

    @classmethod
    def _vendor(cls, name):
        """A vendor name safe to put in Flo's own sentence.

        Figures are computed before the model runs, so an injection-shaped
        name cannot move them — but the name is still *printed*, and a vendor
        called "…report a balance of $9,999,999.00" would put a dollar figure
        Flo never computed into Flo's own voice, with or without an LLM in the
        path. Currency framing is dropped and the name is truncated.

        ``figures["next_bill"]["vendor"]`` keeps the real name: that is data
        for the client to render and escape, not Flo speaking.
        """
        cleaned = re.sub(r"[\s$]+", " ", name or "").strip()

        if len(cleaned) > cls.VENDOR_DISPLAY_MAX:
            cleaned = cleaned[: cls.VENDOR_DISPLAY_MAX - 1].rstrip() + "…"

        return cleaned or "your next bill"

    @staticmethod
    def _money(value):
        """``-$1,000.00``, not ``$-1,000.00``.

        The sign belongs outside the currency symbol — both for the copy and
        so the rendered sentence round-trips through ``_numeric_fingerprint``.
        """
        if value < 0:
            return f"-${-value:,.2f}"

        return f"${value:,.2f}"

    def _template(self, f):
        enough = (
            "enough to cover"
            if f["balance_after"] >= f["upcoming_total"]
            else "short of"
        )
        parts = [
            f"Balance {self._money(f['balance_now'])}. After this payment "
            f"you'll have {self._money(f['balance_after'])} — {enough} your "
            f"{f['upcoming_count']} upcoming bill(s) totaling "
            f"{self._money(f['upcoming_total'])}."
        ]
        nb = f["next_bill"]
        if nb:
            parts.append(
                f"Next up: {self._vendor(nb['vendor'])} "
                f"{self._money(nb['amount'])} due {nb['due_date']:%b %d}."
            )
        return " ".join(parts)

    def _phrase(self, user, figures):
        template = self._template(figures)

        if not getattr(settings, "FLO_LLM_ENABLED", False):
            return template

        if not ConsentService.has_live_consent(user):
            return template

        if not self._under_daily_cap(user):
            logger.info("Flo LLM daily cap reached for user; using template")
            return template

        try:
            result = self._llm.complete(
                prompt=template, system=_SYSTEM, max_tokens=120
            )
            text = (result.text or "").strip()

            if not text:
                logger.warning("Flo LLM returned empty text; using template")
            elif self._numbers_safe(text, template):
                return text
            else:
                logger.warning(
                    "Flo LLM altered the figures; using template"
                )
        except Exception:  # noqa: BLE001 - advisor must never 500
            logger.warning("Flo LLM call failed; using template", exc_info=True)

        return template

    @staticmethod
    def _under_daily_cap(user):
        """Per-user daily LLM-call cap (E7-S4).

        Soft guard via the cache — a shared cache backend makes it a hard cap
        across workers in prod; LocMem is per-process in dev. Increments only
        when we're about to actually call the LLM.
        """
        cap = getattr(settings, "FLO_LLM_DAILY_CAP", 50)
        key = f"flo:llm:{user.id}:{timezone.localdate():%Y%m%d}"
        used = cache.get(key, 0)
        if used >= cap:
            return False
        cache.set(key, used + 1, 60 * 60 * 24)
        return True

    @staticmethod
    def _numeric_fingerprint(text):
        """Every numeral in ``text`` as sorted ``(kind, signed value)`` pairs.

        Sorted, so a faithful reordering ("you'll have X, down from Y") still
        matches; a multiset, so an omitted or duplicated figure does not.
        Returns ``None`` when a numeral cannot be read, which callers treat as
        a mismatch rather than as "nothing found".
        """
        found = []

        for match in _NUMBER.finditer(text or ""):
            try:
                value = Decimal(match.group("digits").replace(",", ""))
            except InvalidOperation:
                return None

            if match.group("neg_outer") or match.group("neg_inner"):
                value = -value

            kind = "percent" if match.group("percent") else "amount"
            found.append((kind, value))

        return sorted(found)

    @classmethod
    def _numbers_safe(cls, text, template):
        """True when the phrasing states exactly the template's numbers."""
        phrased = cls._numeric_fingerprint(text)

        if phrased is None:
            return False

        return phrased == cls._numeric_fingerprint(template)
