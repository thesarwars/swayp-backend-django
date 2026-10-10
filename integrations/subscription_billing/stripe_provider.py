"""Stripe Billing adapter (E9-S1).

Activated by settings alone::

    SUBSCRIPTION_BILLING_PROVIDER=stripe
    STRIPE_SECRET_KEY=sk_...
    STRIPE_PUBLISHABLE_KEY=pk_...
    STRIPE_BILLING_WEBHOOK_SECRET=whsec_...

Test and live keys differ only in the value, so going live is an ``.env``
change and a redeploy. Nothing in ``apps/billing`` knows Stripe exists.

**Customers and prices are found before they are created.** Both are looked up
by a Swayp identifier held in metadata, so a retried subscribe cannot leave a
second customer behind — which would be a customer billed twice — and a
restarted process reuses the price it made last time.

The card never reaches Swayp. The client collects it with a SetupIntent and
sends back only a payment-method id.
"""

from __future__ import annotations

import logging
from decimal import Decimal

from django.conf import settings

from integrations.subscription_billing.base import (
    CardRef,
    InvoiceRef,
    BillingProviderError,
    CardDeclined,
    CustomerRef,
    SetupIntentRef,
    SubscriptionBillingProvider,
    SubscriptionRef,
)

logger = logging.getLogger(__name__)

#: Stripe works in the smallest currency unit, so $49.00 is 4900. Doing this
#: with float() would eventually shave a cent off somebody's invoice.
CENTS = Decimal("100")


def to_minor_units(amount) -> int:
    return int((Decimal(str(amount)) * CENTS).quantize(Decimal("1")))


class StripeSubscriptionBillingProvider(SubscriptionBillingProvider):
    name = "stripe"
    collects_money = True

    def __init__(self):
        import stripe

        key = getattr(settings, "STRIPE_SECRET_KEY", "")

        if not key:
            raise BillingProviderError(
                "STRIPE_SECRET_KEY is not set. Set it, or set "
                "SUBSCRIPTION_BILLING_PROVIDER=mock."
            )

        self._stripe = stripe
        self._client = stripe.StripeClient(key)
        self._publishable = getattr(settings, "STRIPE_PUBLISHABLE_KEY", "")

    # --- error translation ------------------------------------------------

    def _call(self, fn, *args, **kwargs):
        """Run a Stripe call and translate its failures.

        A declined card is the customer's problem and its message is safe to
        show them; everything else is ours and is logged with the request id
        so it can be found in the Stripe dashboard.
        """
        try:
            return fn(*args, **kwargs)
        except self._stripe.CardError as error:
            raise CardDeclined(
                getattr(error, "user_message", None)
                or "Your card was declined."
            ) from error
        except self._stripe.StripeError as error:
            logger.error(
                "stripe call failed (%s): %s",
                getattr(error, "request_id", "no-request-id"),
                error,
            )
            raise BillingProviderError(str(error)) from error

    # --- customers --------------------------------------------------------

    def _search_customer(self, account_id):
        found = self._call(
            self._client.v1.customers.search,
            params={
                "query": f"metadata['swayp_account_id']:'{account_id}'",
                "limit": 1,
            },
        )

        return CustomerRef(id=found.data[0].id) if found.data else None

    def ensure_customer(self, *, account_id, email, name=""):
        """One Stripe customer per Swayp account, ever.

        Two customers for one account means an account billed twice, so the
        idempotency key is the only thing this really leans on — search is
        eventually consistent and a customer created seconds ago may not
        appear in it yet.

        For the key to be reliable the create parameters must never vary,
        because Stripe scopes a key to the parameters it was first used with.
        So the create carries **only** the metadata that identifies the
        account — always byte-identical for a given account — and the email
        and name are set by a follow-up update.

        Sending them on the create instead looked harmless and was not: an
        account retrying after changing its name got IdempotencyError, which
        surfaced as a 503, and the obvious fallback of creating without a key
        silently produced the duplicate customer the key existed to prevent.
        """
        existing = self._search_customer(account_id)

        if existing is None:
            created = self._call(
                self._client.v1.customers.create,
                params={"metadata": {"swayp_account_id": str(account_id)}},
                options={"idempotency_key": f"cus:{account_id}"},
            )
            customer_id = created.id
        else:
            customer_id = existing.id

        # Separate call, so changing details can never disturb the create.
        # Failure here is not worth losing the customer over — it only
        # affects how the row reads in the Stripe dashboard.
        try:
            self._call(
                self._client.v1.customers.update,
                customer_id,
                params={"email": email, "name": name or email},
            )
        except BillingProviderError:
            logger.warning(
                "could not set details on Stripe customer %s", customer_id
            )

        return CustomerRef(id=customer_id)

    # --- prices -----------------------------------------------------------

    def ensure_price(self, *, plan_code, name, amount, currency="usd"):
        """Find or create the recurring price for a plan.

        Keyed on plan code *and* amount, so changing a plan's price creates a
        new Stripe price rather than silently repricing existing subscribers —
        Stripe prices are immutable, and that is the behaviour we want anyway.
        """
        lookup = f"swayp_{plan_code.lower()}_{to_minor_units(amount)}"

        found = self._call(
            self._client.v1.prices.list,
            params={"lookup_keys": [lookup], "limit": 1, "active": True},
        )

        if found.data:
            return found.data[0].id

        created = self._call(
            self._client.v1.prices.create,
            params={
                "currency": currency,
                "unit_amount": to_minor_units(amount),
                "recurring": {"interval": "month"},
                "lookup_key": lookup,
                "product_data": {"name": f"Swayp {name}"},
                "metadata": {"swayp_plan_code": plan_code},
            },
            options={"idempotency_key": f"price:{lookup}"},
        )

        return created.id

    # --- card collection --------------------------------------------------

    def create_setup_intent(self, *, customer_id):
        intent = self._call(
            self._client.v1.setup_intents.create,
            params={
                "customer": customer_id,
                "payment_method_types": ["card"],
                "usage": "off_session",
            },
        )

        return SetupIntentRef(
            client_secret=intent.client_secret,
            publishable_key=self._publishable,
        )

    # --- subscriptions ----------------------------------------------------

    def create_subscription(self, *, customer_id, price_id,
                            payment_method_id="", trial_days=0,
                            idempotency_key=""):
        if payment_method_id:
            attached = self._call(
                self._client.v1.payment_methods.attach,
                payment_method_id,
                params={"customer": customer_id},
            )

            # Use the id the attach came back with, not the one we sent. A
            # shared test token like pm_card_visa becomes a new, customer-
            # specific payment method, and setting the original as the
            # default fails with "the customer does not have a payment
            # method with that ID".
            default_id = self._field(attached, "id") or payment_method_id

            self._call(
                self._client.v1.customers.update,
                customer_id,
                params={
                    "invoice_settings": {
                        "default_payment_method": default_id
                    }
                },
            )

        params = {
            "customer": customer_id,
            "items": [{"price": price_id}],
            # Expanded so the secret the client needs to confirm the first
            # charge arrives in this response rather than having to be
            # chased through a webhook.
            #
            # It is confirmation_secret, not payment_intent: current Stripe
            # API versions dropped latest_invoice.payment_intent, and
            # expanding the old path silently returns nothing — which would
            # strand every subscription at "incomplete", never charged,
            # with no error anywhere to say why.
            "expand": ["latest_invoice.confirmation_secret"],
            "payment_behavior": "default_incomplete",
        }

        if trial_days:
            params["trial_period_days"] = trial_days
            # Without this, a trial reaching its end with no card silently
            # cancels the subscription. create_invoice raises an invoice that
            # goes unpaid instead, which fires invoice.payment_failed, which
            # the billing webhook maps to PAST_DUE — a state the customer can
            # recover from by adding a card. "pause" would leave them in a
            # state this codebase has no handler for.
            params["trial_settings"] = {
                "end_behavior": {"missing_payment_method": "create_invoice"}
            }

        options = (
            {"idempotency_key": idempotency_key} if idempotency_key else None
        )

        sub = self._call(
            self._client.v1.subscriptions.create, params=params, options=options
        )

        return self._to_ref(sub)

    def change_plan(self, *, subscription_id, price_id):
        current = self._call(
            self._client.v1.subscriptions.retrieve, subscription_id
        )
        item_id = current["items"]["data"][0]["id"]

        updated = self._call(
            self._client.v1.subscriptions.update,
            subscription_id,
            params={
                "items": [{"id": item_id, "price": price_id}],
                # Swayp has no proration policy yet (E9 open question), so the
                # change takes effect without a credit or a mid-cycle charge.
                # When the policy lands, this is the one line that changes.
                "proration_behavior": "none",
            },
        )

        return self._to_ref(updated)

    def cancel_subscription(self, *, subscription_id):
        cancelled = self._call(
            self._client.v1.subscriptions.cancel, subscription_id
        )

        return self._to_ref(cancelled)

    # --- card on file (BILLING-1) -----------------------------------------

    def _card(self, payment_method):
        card = self._field(payment_method, "card") if payment_method else None

        if not card:
            return None

        return CardRef(
            brand=str(self._field(card, "brand", "") or ""),
            last4=str(self._field(card, "last4", "") or ""),
            exp_month=int(self._field(card, "exp_month", 0) or 0),
            exp_year=int(self._field(card, "exp_year", 0) or 0),
        )

    def get_default_card(self, *, customer_id):
        customer = self._call(
            self._client.v1.customers.retrieve,
            customer_id,
            params={"expand": ["invoice_settings.default_payment_method"]},
        )
        settings = self._field(customer, "invoice_settings", {}) or {}

        return self._card(self._field(settings, "default_payment_method"))

    def set_default_card(self, *, customer_id, payment_method_id,
                         subscription_id=""):
        attached = self._call(
            self._client.v1.payment_methods.attach,
            payment_method_id,
            params={"customer": customer_id},
        )
        # The attached id, not the one sent: see create_subscription.
        default_id = self._field(attached, "id") or payment_method_id

        self._call(
            self._client.v1.customers.update,
            customer_id,
            params={
                "invoice_settings": {"default_payment_method": default_id}
            },
        )

        # The subscription's own default wins over the customer's, so a
        # subscription created with the old card would keep charging it.
        if subscription_id:
            self._call(
                self._client.v1.subscriptions.update,
                subscription_id,
                params={"default_payment_method": default_id},
            )

        return self._card(attached)

    def list_invoices(self, *, customer_id, limit=20, starting_after=""):
        import datetime as dt

        params = {"customer": customer_id, "limit": max(1, min(limit, 100))}

        if starting_after:
            params["starting_after"] = starting_after

        page = self._call(self._client.v1.invoices.list, params=params)

        def when(seconds):
            if not seconds:
                return None

            return dt.datetime.fromtimestamp(
                int(seconds), tz=dt.timezone.utc
            ).isoformat()

        invoices = []

        for invoice in self._field(page, "data", []) or []:
            transitions = self._field(invoice, "status_transitions", {}) or {}
            invoices.append(
                InvoiceRef(
                    id=self._field(invoice, "id"),
                    number=self._field(invoice, "number", "") or "",
                    status=self._field(invoice, "status", "") or "",
                    total=Decimal(self._field(invoice, "total", 0) or 0)
                    / 100,
                    currency=(self._field(invoice, "currency", "usd") or "usd"),
                    created=when(self._field(invoice, "created")),
                    period_start=when(self._field(invoice, "period_start")),
                    period_end=when(self._field(invoice, "period_end")),
                    paid_at=when(self._field(transitions, "paid_at")),
                    pdf_url=self._field(invoice, "invoice_pdf", "") or "",
                    hosted_url=(
                        self._field(invoice, "hosted_invoice_url", "") or ""
                    ),
                )
            )

        return invoices, bool(self._field(page, "has_more", False))

    def retry_latest_invoice(self, *, subscription_id):
        subscription = self._call(
            self._client.v1.subscriptions.retrieve,
            subscription_id,
            params={"expand": ["latest_invoice"]},
        )
        invoice = self._field(subscription, "latest_invoice")

        if not invoice or self._field(invoice, "status") != "open":
            return False

        paid = self._call(
            self._client.v1.invoices.pay, self._field(invoice, "id")
        )

        return self._field(paid, "status") == "paid"

    def set_cancel_at_period_end(self, *, subscription_id, cancel):
        updated = self._call(
            self._client.v1.subscriptions.update,
            subscription_id,
            {"cancel_at_period_end": bool(cancel)},
        )

        return self._to_ref(updated)

    # --- fees -------------------------------------------------------------

    def add_invoice_item(self, *, customer_id, amount, description,
                         currency="usd", idempotency_key=""):
        options = (
            {"idempotency_key": idempotency_key} if idempotency_key else None
        )

        item = self._call(
            self._client.v1.invoice_items.create,
            params={
                "customer": customer_id,
                "amount": to_minor_units(amount),
                "currency": currency,
                "description": description,
            },
            options=options,
        )

        return item.id

    # --- helpers ----------------------------------------------------------

    @staticmethod
    def _field(obj, key, default=None):
        """Read a key off a Stripe object.

        ``StripeObject`` routes attribute access through ``__getattr__``, so
        ``obj.get(...)`` raises AttributeError rather than behaving like a
        dict — subscript access is the only form that works on both a
        StripeObject and a plain dict, which is what the tests hand it.
        """
        if obj is None:
            return default

        try:
            value = obj[key]
        except (KeyError, TypeError, AttributeError):
            return default

        return default if value is None else value

    def _client_secret(self, invoice):
        """The secret the client confirms the first charge with.

        Two shapes, because the field moved: current API versions put it on
        ``confirmation_secret`` and older ones on ``payment_intent``. Reading
        both means the adapter survives an account being on either.
        """
        confirmation = self._field(invoice, "confirmation_secret", {})
        secret = self._field(confirmation, "client_secret", "")

        if secret:
            return secret

        intent = self._field(invoice, "payment_intent", {})

        return self._field(intent, "client_secret", "") or ""

    def _to_ref(self, sub):
        invoice = self._field(sub, "latest_invoice", {})

        # current_period_end sits on the subscription in older API versions
        # and on the item in newer ones. Read both rather than pin a version:
        # a missing renewal date is not worth failing a subscription over.
        period_end = self._field(sub, "current_period_end")

        if period_end is None:
            items = self._field(sub, "items", {})
            data = self._field(items, "data", []) or []

            if data:
                period_end = self._field(data[0], "current_period_end")

        return SubscriptionRef(
            id=self._field(sub, "id", ""),
            status=self._field(sub, "status", "") or "",
            current_period_end=str(period_end) if period_end else None,
            client_secret=self._client_secret(invoice),
        )
