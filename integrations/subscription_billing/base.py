"""Subscription billing provider interface (E9-S1).

This is the seam between "what the customer is entitled to" and "who collects
the money". Swayp owns the first — plans, allowances, fees, the invoice
preview — and a provider owns the second.

Keeping them apart is what let the whole commercial layer ship and be correct
before any card processor existed, and it is what makes swapping test
credentials for live ones a change to ``.env`` rather than to code.

Two rules the adapters follow:

* **Idempotent by name.** ``ensure_customer`` and ``ensure_price`` are called
  on every subscribe. They must return the existing object rather than
  creating a second one, because a duplicated customer means a customer billed
  twice.
* **Failures raise ``BillingProviderError``.** Callers decide whether that is
  fatal. Creating a subscription is; recording an accrued fee is not.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from decimal import Decimal
from typing import Optional


class BillingProviderError(Exception):
    """The provider refused or was unreachable."""


class CardDeclined(BillingProviderError):
    """The customer's card was declined.

    Separate from the generic error because it is the customer's problem to
    fix, not an outage — the message is safe to show them.
    """


@dataclass(frozen=True)
class CustomerRef:
    id: str


@dataclass(frozen=True)
class SetupIntentRef:
    """What the client needs to collect a card without it touching Swayp."""

    client_secret: str
    publishable_key: str = ""


@dataclass(frozen=True)
class SubscriptionRef:
    id: str
    #: Provider-side status, normalised to Swayp's vocabulary by the caller.
    status: str
    current_period_end: Optional[str] = None
    #: Present when the card needs 3-D Secure before the first charge clears.
    client_secret: str = ""


@dataclass(frozen=True)
class CardRef:
    """The card on file, as safe to show: never a number or a token."""

    brand: str
    last4: str
    exp_month: int
    exp_year: int


@dataclass(frozen=True)
class InvoiceRef:
    """One past invoice, as the billing history shows it (BILLING-2)."""

    id: str
    number: str
    status: str
    total: Decimal
    currency: str
    created: Optional[str]
    period_start: Optional[str]
    period_end: Optional[str]
    paid_at: Optional[str]
    pdf_url: str
    hosted_url: str


class SubscriptionBillingProvider(ABC):
    name = "base"

    #: False for the mock, so callers can tell "nothing to collect" from
    #: "collection failed" without inspecting the class.
    collects_money = False

    @abstractmethod
    def ensure_customer(self, *, account_id: str, email: str,
                        name: str = "") -> CustomerRef:
        """The provider-side customer for this account, created if absent."""

    @abstractmethod
    def ensure_price(self, *, plan_code: str, name: str, amount: Decimal,
                     currency: str = "usd") -> str:
        """The provider-side recurring price for a plan, created if absent.

        Created from Swayp's own plan table rather than configured by hand in
        a dashboard, so the BRD numbers stay the single source of truth and
        going live needs no manual setup.
        """

    @abstractmethod
    def create_setup_intent(self, *, customer_id: str) -> SetupIntentRef:
        """Start card collection. The card never reaches Swayp's servers."""

    @abstractmethod
    def create_subscription(self, *, customer_id: str, price_id: str,
                            payment_method_id: str = "",
                            trial_days: int = 0,
                            idempotency_key: str = "") -> SubscriptionRef:
        """``trial_days`` holds the first charge. A trialling subscription is
        valid without a payment method, which is what makes the signup
        screen's "no card needed" true."""

    @abstractmethod
    def change_plan(self, *, subscription_id: str,
                    price_id: str) -> SubscriptionRef:
        ...

    @abstractmethod
    def cancel_subscription(self, *, subscription_id: str) -> SubscriptionRef:
        ...

    @abstractmethod
    def get_default_card(self, *, customer_id: str) -> Optional[CardRef]:
        """The customer's default card, or None (BILLING-1)."""
        ...

    @abstractmethod
    def set_default_card(self, *, customer_id: str, payment_method_id: str,
                         subscription_id: str = "") -> CardRef:
        """Attach a card collected against a SetupIntent and make it the
        default for the customer and the subscription (BILLING-1)."""
        ...

    @abstractmethod
    def list_invoices(self, *, customer_id: str, limit: int = 20,
                      starting_after: str = "") -> tuple[list, bool]:
        """Newest first. Returns (invoices, has_more); page on with the last
        invoice's id as starting_after."""
        ...

    @abstractmethod
    def retry_latest_invoice(self, *, subscription_id: str) -> bool:
        """Try the subscription's open invoice again now. True if paid."""
        ...

    @abstractmethod
    def set_cancel_at_period_end(self, *, subscription_id: str,
                                 cancel: bool) -> SubscriptionRef:
        """Schedule (True) or withdraw (False) cancellation at the end of the
        current period. The subscription stays active until then."""
        ...

    @abstractmethod
    def add_invoice_item(self, *, customer_id: str, amount: Decimal,
                         description: str, currency: str = "usd",
                         idempotency_key: str = "") -> str:
        """Put an accrued fee onto the customer's next invoice.

        Per-transaction fees are billed in arrears with the subscription
        rather than charged one by one, which is both cheaper in processor
        fees and what the invoice preview already shows.
        """
