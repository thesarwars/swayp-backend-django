"""Offline subscription billing (E9-S1).

The default. Deterministic ids derived from the input, so the same account
always maps to the same customer and re-running a flow in tests or a demo does
not accumulate objects.

``collects_money`` is False, which is the honest signal: subscriptions here
are entitlements, not payments. Nothing is charged and nothing can decline.
"""

from __future__ import annotations

import hashlib
from decimal import Decimal

from integrations.subscription_billing.base import (
    CustomerRef,
    SetupIntentRef,
    SubscriptionBillingProvider,
    SubscriptionRef,
)


def _stable(prefix: str, *parts) -> str:
    digest = hashlib.sha256("|".join(str(p) for p in parts).encode())

    return f"{prefix}_mock_{digest.hexdigest()[:20]}"


class MockSubscriptionBillingProvider(SubscriptionBillingProvider):
    name = "mock"
    collects_money = False

    def ensure_customer(self, *, account_id, email, name=""):
        return CustomerRef(id=_stable("cus", account_id))

    def ensure_price(self, *, plan_code, name, amount, currency="usd"):
        # Amount is part of the id so a price change produces a new one, the
        # same way it would at a real provider.
        return _stable("price", plan_code, amount, currency)

    def create_setup_intent(self, *, customer_id):
        return SetupIntentRef(
            client_secret=_stable("seti", customer_id) + "_secret",
            publishable_key="pk_mock",
        )

    def create_subscription(self, *, customer_id, price_id,
                            payment_method_id="", idempotency_key=""):
        return SubscriptionRef(
            id=_stable("sub", customer_id, price_id),
            status="active",
        )

    def change_plan(self, *, subscription_id, price_id):
        return SubscriptionRef(id=subscription_id, status="active")

    def cancel_subscription(self, *, subscription_id):
        return SubscriptionRef(id=subscription_id, status="canceled")

    def add_invoice_item(self, *, customer_id, amount, description,
                         currency="usd", idempotency_key=""):
        return _stable("ii", customer_id, description, Decimal(amount))
