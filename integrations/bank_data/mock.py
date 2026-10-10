"""Deterministic canned bank data (E1-S4 / E5-S2).

Generates a realistic 12-month history so the recurring-bill detector has
something to actually cluster: four clean recurring vendors, one that varies
in amount, one that only appears twice (must be rejected — the rule is 3+
occurrences), and a scatter of one-off purchases as noise.

Everything is derived from a fixed anchor date, so a scan produces the same
candidates every run and golden tests stay stable.
"""

import datetime as dt
from decimal import Decimal

from integrations.bank_data.base import (
    BankAccountInfo,
    BankDataProvider,
    ExchangeResult,
    Institution,
    LinkToken,
    RecurringCandidate,
    Transaction,
)

#: History is generated backwards from here, not from today, so fixtures do
#: not drift as the calendar moves.
ANCHOR = dt.date(2026, 7, 1)

#: Institutions offered by the mock link flow (836:8618).
INSTITUTIONS = {
    "chase": ("Chase Bank", "Chase Business Checking", "4821"),
    "bofa": ("Bank of America", "BofA Business Advantage", "7734"),
    "wellsfargo": ("Wells Fargo", "Wells Fargo Business", "1192"),
    "usbank": ("U.S. Bank", "U.S. Bank Silver Checking", "5580"),
}

DEFAULT_INSTITUTION = "chase"

#: (vendor, amount, day-of-month, months of history, per-month drift)
_RECURRING = [
    ("WeWork", Decimal("3200.00"), 1, 12, Decimal("0")),
    ("Verizon Business", Decimal("389.00"), 15, 12, Decimal("0")),
    ("Amazon Web Services", Decimal("892.00"), 14, 9, Decimal("0")),
    # Varies slightly month to month — must still cluster, since real bills
    # rarely land on exactly the same cent.
    ("Con Edison", Decimal("214.00"), 22, 8, Decimal("3.50")),
]

#: Appears only twice, so it must NOT become a candidate.
_TOO_FEW = ("Blue Bottle Coffee", Decimal("48.00"), 9, 2)

#: One-off noise the detector has to ignore.
_ONE_OFFS = [
    ("Staples", Decimal("122.45"), dt.date(2026, 3, 4)),
    ("Delta Air Lines", Decimal("845.20"), dt.date(2026, 4, 19)),
    ("Apple Store", Decimal("2399.00"), dt.date(2026, 5, 27)),
]

_DAYS_IN_MONTH = (31, 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31)


def _last_day(year: int, month: int) -> int:
    if month == 2 and (year % 4 == 0 and (year % 100 != 0 or year % 400 == 0)):
        return 29
    return _DAYS_IN_MONTH[month - 1]


def _shift_months(anchor: dt.date, months_back: int, day: int) -> dt.date:
    total = anchor.month - 1 - months_back
    year = anchor.year + total // 12
    month = total % 12 + 1

    # Clamp so a day-31 bill still lands inside February.
    return dt.date(year, month, min(day, _last_day(year, month)))


class MockBankDataProvider(BankDataProvider):

    name = "mock"

    def create_link_token(self, *, user_ref: str, platform=None) -> LinkToken:
        return LinkToken(token=f"link-mock-{user_ref}", expiration=None)

    def exchange_public_token(self, *, public_token: str) -> ExchangeResult:
        # The institution can be steered from the public token for testing:
        # "public-mock-bofa" links Bank of America.
        key = DEFAULT_INSTITUTION

        for candidate in INSTITUTIONS:
            if candidate in (public_token or "").lower():
                key = candidate
                break

        institution, account_name, mask = INSTITUTIONS[key]

        return ExchangeResult(
            item_id=f"mock-item-{key}",
            access_token=f"mock-access-token-{key}",
            institution_name=institution,
            accounts=(
                BankAccountInfo(
                    account_id=f"mock-acc-{mask}",
                    mask=mask,
                    name=account_name,
                    type="checking",
                    balance=Decimal("41200.00"),
                ),
                BankAccountInfo(
                    account_id=f"mock-sav-{mask}",
                    mask=f"{(int(mask) + 1) % 10000:04d}",
                    name=f"{institution} Savings",
                    type="savings",
                    balance=Decimal("18750.00"),
                ),
            ),
        )

    def get_transactions(
        self, *, access_token: str, months: int = 12
    ) -> tuple[Transaction, ...]:
        months = max(1, min(months, 12))

        transactions = []
        counter = 0

        def add(name, amount, posted_on):
            nonlocal counter
            counter += 1
            transactions.append(
                Transaction(
                    transaction_id=f"mock-tx-{counter}",
                    posted_on=posted_on,
                    name=name,
                    amount=amount,
                )
            )

        for vendor, amount, day, history, drift in _RECURRING:
            for index in range(min(history, months)):
                add(
                    vendor,
                    amount + drift * index,
                    _shift_months(ANCHOR, index, day),
                )

        vendor, amount, day, history = _TOO_FEW
        for index in range(min(history, months)):
            add(vendor, amount, _shift_months(ANCHOR, index, day))

        earliest = _shift_months(ANCHOR, months - 1, 1)
        for name, amount, posted_on in _ONE_OFFS:
            if posted_on >= earliest:
                add(name, amount, posted_on)

        return tuple(
            sorted(transactions, key=lambda t: t.posted_on, reverse=True)
        )

    def get_recurring(
        self, *, access_token: str
    ) -> tuple[RecurringCandidate, ...]:
        """Provider-side recurring hints.

        Swayp does not rely on these — detection runs deterministically over
        the transaction history (E5-S4) so the rules are ours and testable.
        """
        return tuple(
            RecurringCandidate(vendor, amount, "MONTHLY", day, history)
            for vendor, amount, day, history, _ in _RECURRING
        )

    def get_balance(self, *, access_token: str, account_id: str) -> Decimal:
        return Decimal("41200.00")

    def create_processor_token(
        self, *, access_token: str, account_id: str, processor: str
    ) -> str:
        return f"processor-{processor}-{account_id}"

    def search_institutions(self, *, query: str):
        """Substring match over the canned four, so the picker works offline."""
        needle = (query or "").strip().lower()

        return tuple(
            Institution(
                institution_id=key,
                name=name,
                logo=None,
                subtitle=account_name,
            )
            for key, (name, account_name, _mask) in INSTITUTIONS.items()
            if not needle or needle in name.lower() or needle in key
        )

    def verify_webhook(self, *, raw_body: bytes, header_value: str) -> None:
        """Shared-secret HMAC, so the flow can be exercised without Plaid.

        Deliberately not a no-op: a mock that accepts anything would let a
        missing signature reach the handler in every test, and the one thing
        this guards is that unverified callbacks never do.
        """
        import hashlib
        import hmac

        from django.conf import settings

        secret = getattr(settings, "WEBHOOK_SECRETS", {}).get("PLAID") or ""
        expected = hmac.new(
            secret.encode(), raw_body, hashlib.sha256
        ).hexdigest()

        if not secret or not hmac.compare_digest(expected, header_value):
            raise ValueError("Mock webhook signature mismatch.")

    def remove_item(self, *, access_token: str) -> None:
        # Deterministic mock — no remote item to revoke.
        return None
