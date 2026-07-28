"""Bank-data provider interface (Plaid). Read-only; never moves money."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from typing import Optional


@dataclass(frozen=True)
class LinkToken:
    token: str
    expiration: Optional[str] = None


@dataclass(frozen=True)
class BankAccountInfo:
    account_id: str
    mask: str
    name: str
    type: str
    balance: Decimal


@dataclass(frozen=True)
class ExchangeResult:
    item_id: str
    access_token: str
    institution_name: str
    accounts: tuple[BankAccountInfo, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class Transaction:
    transaction_id: str
    posted_on: date
    name: str
    amount: Decimal


@dataclass(frozen=True)
class RecurringCandidate:
    vendor_name: str
    amount: Decimal
    cadence: str
    due_day: int
    occurrences: int


class BankDataProvider(ABC):
    name = "base"

    @abstractmethod
    def create_link_token(self, *, user_ref: str) -> LinkToken:
        ...

    @abstractmethod
    def exchange_public_token(self, *, public_token: str) -> ExchangeResult:
        ...

    @abstractmethod
    def get_transactions(
        self, *, access_token: str, months: int = 12
    ) -> tuple[Transaction, ...]:
        ...

    @abstractmethod
    def get_recurring(
        self, *, access_token: str
    ) -> tuple[RecurringCandidate, ...]:
        ...

    @abstractmethod
    def get_balance(self, *, access_token: str, account_id: str) -> Decimal:
        ...

    @abstractmethod
    def create_processor_token(
        self, *, access_token: str, account_id: str, processor: str
    ) -> str:
        ...

    @abstractmethod
    def remove_item(self, *, access_token: str) -> None:
        """Revoke the linked item at the provider (Plaid ``/item/remove``).

        Called on disconnect so a 'disconnected' connection is actually dead
        at the provider, not just locally flagged.
        """
        ...
