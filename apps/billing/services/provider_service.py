"""Bridge between Swayp's subscription records and the billing provider.

Everything provider-shaped lives here so ``SubscriptionService`` keeps talking
about plans and cycles. Three rules hold throughout:

* **Entitlement first, collection second.** Swayp decides what a customer is
  entitled to; the provider decides whether the money arrived. A provider
  outage must never leave a paying customer locked out of the product, so a
  failure to *record* a fee is swallowed while a failure to *start* a
  subscription is raised.
* **The mock is not a lesser Stripe.** It collects nothing by design, so the
  code asks ``collects_money`` rather than checking the provider's name.
* **Provider ids are cached on our rows.** A customer or price is looked up
  once and remembered, because creating a second customer means billing
  someone twice.
"""

import logging

from django.db import transaction
from rest_framework.exceptions import APIException, ValidationError

from apps.billing.models import Plan
from integrations.factory import get_subscription_billing_provider
from integrations.subscription_billing.base import (
    BillingProviderError,
    CardDeclined,
)
from apps.common.error_codes import CARD_DECLINED

logger = logging.getLogger(__name__)


class ServiceUnavailable(APIException):
    """The billing provider is unreachable.

    503 rather than 500: nothing is broken in Swayp and the customer
    should retry, which is a different instruction from "contact
    support".
    """

    status_code = 503
    default_detail = "Billing is temporarily unavailable."
    default_code = "billing_unavailable"

#: Stripe's subscription states mapped onto Swayp's. ``incomplete`` stays
#: ACTIVE deliberately: the customer has chosen a plan and Swayp has granted
#: the entitlement, and taking it away while a 3-D Secure prompt is on screen
#: would be punishing them for their bank's security step. A genuine failure
#: arrives later as ``past_due`` or ``unpaid``.
PROVIDER_STATUS_MAP = {
    "active": "ACTIVE",
    "trialing": "ACTIVE",
    "incomplete": "ACTIVE",
    "past_due": "PAST_DUE",
    "unpaid": "PAST_DUE",
    "incomplete_expired": "CANCELLED",
    "canceled": "CANCELLED",
}


def swayp_status(provider_status, default=None):
    """Translate a provider status into Swayp's vocabulary.

    Module-level because the webhook needs it without constructing a
    provider — building a Stripe client just to read a dictionary would make
    an unrelated credential problem look like a webhook failure.
    """
    return PROVIDER_STATUS_MAP.get(provider_status, default)


class BillingProviderService:

    def __init__(self, provider=None):
        self.provider = provider or get_subscription_billing_provider()

    @property
    def collects_money(self):
        return getattr(self.provider, "collects_money", False)

    @property
    def publishable_key(self):
        """The processor's public key for the client SDK, or "" (BILLING-3).
        Public by design; never a secret."""
        if not self.collects_money:
            return ""

        return getattr(self.provider, "_publishable", "") or ""

    def swayp_status(self, provider_status, default=None):
        return swayp_status(provider_status, default)

    # --- customer and price -----------------------------------------------

    def customer_id(self, subscription):
        """The provider customer for this account, remembered on the row."""
        if subscription.provider_customer_id:
            return subscription.provider_customer_id

        account = subscription.account
        customer = self.provider.ensure_customer(
            account_id=str(account.pk),
            email=account.email or "",
            name=f"{account.first_name} {account.last_name}".strip(),
        )

        subscription.provider_customer_id = customer.id
        subscription.save(
            update_fields=["provider_customer_id", "updated_at"]
        )

        return customer.id

    def price_id(self, plan):
        """The provider price for this plan, remembered on the row.

        Cached against ``effective_price``-free list price: a locked customer
        keeps their own price through ``locked_price``, and creating a second
        provider price per customer would be unmanageable.
        """
        if plan.provider_price_id:
            return plan.provider_price_id

        price = self.provider.ensure_price(
            plan_code=plan.code,
            name=plan.name,
            amount=plan.monthly_price,
        )

        Plan.objects.filter(pk=plan.pk).update(provider_price_id=price)
        plan.provider_price_id = price

        return price

    # --- card collection --------------------------------------------------

    def setup_intent(self, subscription):
        return self.provider.create_setup_intent(
            customer_id=self.customer_id(subscription)
        )

    # --- subscription lifecycle -------------------------------------------

    @transaction.atomic
    def start(self, subscription, *, payment_method_id="", trial_days=0):
        """Open the provider-side subscription.

        Raises on failure, so the surrounding transaction rolls the Swayp
        subscription back too. A subscription the customer believes they
        bought but that no provider knows about is worse than a visible error.
        """
        if not self.collects_money:
            return None

        try:
            ref = self.provider.create_subscription(
                customer_id=self.customer_id(subscription),
                price_id=self.price_id(subscription.plan),
                payment_method_id=payment_method_id,
                # Stripe holds the first charge for this many days. Passing it
                # here rather than scheduling our own is what makes "no card
                # needed" true: a trialling subscription is valid without a
                # payment method until the trial ends.
                trial_days=trial_days,
                # One provider subscription per Swayp subscription, so a
                # retried request cannot open a second one and bill twice.
                idempotency_key=f"sub:{subscription.pk}",
            )
        except CardDeclined as error:
            # The customer's problem and fixable by them, so it is a field
            # error on what they submitted — not a 402, which the client
            # renders as "upgrade your plan" and would be actively misleading
            # when the plan is fine and the card is not.
            raise ValidationError(
                {"payment_method_id": str(error)}, code=CARD_DECLINED
            )
        except BillingProviderError as error:
            logger.error("could not start subscription: %s", error)

            raise ServiceUnavailable(
                "Our billing provider is temporarily unavailable. "
                "Your card has not been charged — please try again."
            )

        self._apply(subscription, ref)

        # Stashed on the instance rather than the row: it is a short-lived
        # one-use secret for this response only, and persisting it would be
        # storing a credential we have no reason to keep.
        subscription.pending_client_secret = ref.client_secret

        return ref

    @transaction.atomic
    def change_plan(self, subscription):
        if not self.collects_money or not subscription.provider_subscription_id:
            return None

        ref = self.provider.change_plan(
            subscription_id=subscription.provider_subscription_id,
            price_id=self.price_id(subscription.plan),
        )

        self._apply(subscription, ref)

        return ref

    # --- card on file (BILLING-1) -----------------------------------------

    def card(self, subscription):
        """The default card, or None when there is none or nothing collects."""
        if not self.collects_money or subscription is None:
            return None

        return self.provider.get_default_card(
            customer_id=self.customer_id(subscription)
        )

    def invoices(self, subscription, *, limit=20, starting_after=""):
        """Past invoices, newest first, and whether more exist (BILLING-2).
        Empty when nothing collects money: no invoices were ever issued."""
        if not self.collects_money or subscription is None:
            return [], False

        try:
            return self.provider.list_invoices(
                customer_id=self.customer_id(subscription),
                limit=limit,
                starting_after=starting_after,
            )
        except BillingProviderError as error:
            raise ServiceUnavailable() from error

    def replace_card(self, subscription, payment_method_id):
        """Make a newly collected card the default, and settle a past-due
        balance with it straight away rather than waiting for Stripe's next
        retry. A decline is the customer's to fix, so it is a field error."""
        from rest_framework.exceptions import ValidationError

        from apps.billing.models import SubscriptionStatus

        if not self.collects_money:
            raise ValidationError(
                {"payment_method_id": "No payment processor is configured."}
            )

        try:
            card = self.provider.set_default_card(
                customer_id=self.customer_id(subscription),
                payment_method_id=payment_method_id,
                subscription_id=subscription.provider_subscription_id,
            )

            if (
                subscription.status == SubscriptionStatus.PAST_DUE
                and subscription.provider_subscription_id
                and self.provider.retry_latest_invoice(
                    subscription_id=subscription.provider_subscription_id
                )
            ):
                subscription.status = SubscriptionStatus.ACTIVE
                subscription.save(update_fields=["status", "updated_at"])

        except CardDeclined as error:
            raise ValidationError(
                {"payment_method_id": [str(error) or "The card was declined."]},
                code=CARD_DECLINED,
            ) from error

        return card

    def schedule_cancel(self, subscription, *, cancel=True):
        """Ask the provider to end (or keep) the subscription at period end.

        Unlike an immediate cancel, a failure here raises: if the provider
        never hears it, it renews and charges a customer who was told their
        plan ends, which is worse than asking them to try again.
        """
        if not self.collects_money or not subscription.provider_subscription_id:
            return None

        try:
            ref = self.provider.set_cancel_at_period_end(
                subscription_id=subscription.provider_subscription_id,
                cancel=cancel,
            )
        except BillingProviderError as error:
            logger.exception(
                "provider cancel scheduling failed for subscription %s",
                subscription.pk,
            )
            raise ServiceUnavailable(
                "Couldn't reach the payment provider. Try again in a moment."
            ) from error

        self._apply(subscription, ref)

        return ref

    def cancel(self, subscription):
        """Cancel provider-side. Never blocks the Swayp-side cancellation.

        A customer who asked to cancel must end up cancelled here even if the
        provider is unreachable; the alternative is telling them it failed
        while continuing to bill them. The mismatch is logged and is
        reconcilable from ``provider_subscription_id``.
        """
        if not self.collects_money or not subscription.provider_subscription_id:
            return None

        try:
            ref = self.provider.cancel_subscription(
                subscription_id=subscription.provider_subscription_id
            )
        except BillingProviderError:
            logger.exception(
                "provider cancel failed for subscription %s (%s); "
                "Swayp-side cancellation stands",
                subscription.pk,
                subscription.provider_subscription_id,
            )

            return None

        self._apply(subscription, ref)

        return ref

    # --- fees -------------------------------------------------------------

    def record_fee(self, fee):
        """Put an accrued fee on the customer's next invoice.

        Deliberately swallows failures. The fee is already in Swayp's ledger,
        which is what the invoice preview reads and what "100% of missed
        guarantees refunded" is measured from; a provider hiccup must not
        break the payment that generated it.
        """
        subscription = fee.subscription

        if not self.collects_money or not subscription.provider_customer_id:
            return None

        try:
            return self.provider.add_invoice_item(
                customer_id=subscription.provider_customer_id,
                amount=fee.amount,
                description=(
                    f"{fee.get_kind_display()} — "
                    f"{fee.payment.transaction_reference}"
                ),
                # Keyed on the fee, so a retry cannot bill it twice.
                idempotency_key=f"fee:{fee.pk}",
            )
        except Exception:
            logger.exception(
                "could not record fee %s with the provider; "
                "it remains in the Swayp ledger",
                fee.pk,
            )

            return None

    # --- helpers ----------------------------------------------------------

    def _apply(self, subscription, ref):
        from apps.billing.models import SubscriptionStatus

        subscription.provider_subscription_id = ref.id
        subscription.provider_status = ref.status

        mapped = self.swayp_status(ref.status)
        fields = [
            "provider_subscription_id", "provider_status", "updated_at",
        ]

        if mapped is not None and mapped != subscription.status:
            # Never resurrect a cancelled subscription from a stale provider
            # message; cancellation is a decision, not an observation.
            if subscription.status != SubscriptionStatus.CANCELLED:
                subscription.status = mapped
                fields.append("status")

        subscription.save(update_fields=fields)

        return subscription
