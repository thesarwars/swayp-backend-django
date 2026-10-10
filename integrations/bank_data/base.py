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
class Institution:
    """One row of the bank picker."""

    institution_id: str
    name: str
    logo: Optional[str] = None
    #: The grey line under the name — "JPMorgan Chase · 70M+ customers" on the
    #: design. Providers rarely give this, so it is optional rather than
    #: invented.
    subtitle: str = ""


@dataclass(frozen=True)
class RecurringCandidate:
    vendor_name: str
    amount: Decimal
    cadence: str
    due_day: int
    occurrences: int


class BankDataProviderError(Exception):
    """The provider could not answer. Ours to fix, or theirs."""


class BankReauthRequired(BankDataProviderError):
    """The link is alive but the user has to log in again.

    Plaid's ``ITEM_LOGIN_REQUIRED``, which is what a changed bank password
    looks like from here. Separate from the generic error because it is not a
    fault: nobody can fix it but the user, and ``BankConnection.status``
    already has somewhere to record it. Reported as a 500 it would send an
    engineer to the logs for a thing only the account holder can resolve.
    """


class BankDataNotReady(BankDataProviderError):
    """The link is good; the data has not finished arriving.

    Plaid's ``PRODUCT_NOT_READY``. An item is usable the moment it is
    exchanged, but transactions are pulled asynchronously afterwards — so a
    scan started immediately after linking asks for history that does not
    exist yet. This is the normal first-connect path, not a fault, and the
    caller should wait for the provider's webhook (or retry) rather than
    record the scan as failed.
    """


class BankDataProvider(ABC):
    name = "base"

    @abstractmethod
    def create_link_token(
        self, *, user_ref: str, platform: Optional[str] = None
    ) -> LinkToken:
        """``platform`` is ``ios``, ``android``, ``web`` or None (treated as
        web). It decides how an OAuth bank hands the user back to the app."""
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

    def search_institutions(self, *, query: str) -> tuple[Institution, ...]:
        """Institutions matching a typed query, for a native bank picker.

        Not abstract for the same reason as verify_webhook: a provider that
        cannot search should say so rather than return an empty list, which
        reads as "no banks match" and sends the user looking for a typo.
        """
        raise NotImplementedError(
            f"{type(self).__name__} cannot search institutions."
        )

    def verify_webhook(self, *, raw_body: bytes, header_value: str) -> None:
        """Prove a callback came from the provider. Raise if it did not.

        Not abstract: a provider with no callbacks has nothing to implement,
        and the default refuses rather than returning quietly — an
        unimplemented check that returns None would look exactly like a
        passing one.
        """
        raise NotImplementedError(
            f"{type(self).__name__} cannot verify webhooks."
        )

    @abstractmethod
    def remove_item(self, *, access_token: str) -> None:
        """Revoke the linked item at the provider (Plaid ``/item/remove``).

        Called on disconnect so a 'disconnected' connection is actually dead
        at the provider, not just locally flagged.
        """
        ...
