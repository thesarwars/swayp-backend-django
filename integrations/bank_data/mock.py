import datetime as dt
from decimal import Decimal

from integrations.bank_data.base import (
    BankAccountInfo,
    BankDataProvider,
    ExchangeResult,
    LinkToken,
    RecurringCandidate,
    Transaction,
)


class MockBankDataProvider(BankDataProvider):
    """Deterministic canned bank data — Chase ****4821 with 3 recurring bills."""

    name = "mock"

    def create_link_token(self, *, user_ref: str) -> LinkToken:
        return LinkToken(token=f"link-mock-{user_ref}", expiration=None)

    def exchange_public_token(self, *, public_token: str) -> ExchangeResult:
        account = BankAccountInfo(
            account_id="mock-acc-4821",
            mask="4821",
            name="Chase Business Checking",
            type="checking",
            balance=Decimal("41200.00"),
        )
        return ExchangeResult(
            item_id="mock-item-1",
            access_token="mock-access-token",
            institution_name="Chase Bank",
            accounts=(account,),
        )

    def get_transactions(
        self, *, access_token: str, months: int = 12
    ) -> tuple[Transaction, ...]:
        return (
            Transaction(
                transaction_id="t1",
                posted_on=dt.date(2026, 1, 1),
                name="WeWork",
                amount=Decimal("3200.00"),
            ),
            Transaction(
                transaction_id="t2",
                posted_on=dt.date(2026, 1, 15),
                name="Verizon Business",
                amount=Decimal("389.00"),
            ),
        )

    def get_recurring(
        self, *, access_token: str
    ) -> tuple[RecurringCandidate, ...]:
        return (
            RecurringCandidate("WeWork", Decimal("3200.00"), "MONTHLY", 1, 12),
            RecurringCandidate(
                "Verizon Business", Decimal("389.00"), "MONTHLY", 15, 12
            ),
            RecurringCandidate(
                "Amazon Web Services", Decimal("892.00"), "MONTHLY", 14, 9
            ),
        )

    def get_balance(self, *, access_token: str, account_id: str) -> Decimal:
        return Decimal("41200.00")

    def create_processor_token(
        self, *, access_token: str, account_id: str, processor: str
    ) -> str:
        return f"processor-{processor}-{account_id}"
