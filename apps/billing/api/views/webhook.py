"""Stripe Billing webhook (E9-S1).

Separate from the payment-rail webhooks under ``apps/webhooks`` on purpose:

* it signs differently — Stripe sends ``Stripe-Signature: t=…,v1=…`` with a
  timestamp inside the signed payload, not the plain HMAC hex the rails use;
* it is about *subscriptions*, not money movement, so it has no business
  sharing the rail dedupe table or its state machine.

Delivery is at-least-once and out of order, so every handler is written to be
applied twice without harm.
"""

import json
import logging

from django.conf import settings
from drf_spectacular.utils import extend_schema
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.billing.models import Subscription, SubscriptionStatus
from apps.billing.services.provider_service import swayp_status
from apps.common.error_codes import INVALID_SIGNATURE
from apps.common.responses import ApiResponse

logger = logging.getLogger(__name__)

#: Events that change what Swayp shows. Everything else is acknowledged and
#: ignored — Stripe sends a great deal that is not our business, and 400-ing
#: it would make Stripe retry forever and eventually disable the endpoint.
HANDLED = {
    "invoice.paid",
    "invoice.payment_succeeded",
    "invoice.payment_failed",
    "customer.subscription.updated",
    "customer.subscription.deleted",
}


class SignatureError(Exception):
    pass


def verify_stripe_signature(*, raw_body, signature_header, secret):
    """Verify using Stripe's own construction.

    Delegated to the SDK rather than reimplemented: it handles the timestamp
    tolerance that stops a captured payload being replayed days later, and
    hand-rolling that is how replay windows get left open.
    """
    if not secret:
        raise SignatureError(
            "No Stripe billing webhook secret configured."
        )

    if not signature_header:
        raise SignatureError("Missing Stripe-Signature header.")

    try:
        import stripe
    except ImportError as error:
        raise SignatureError("Stripe SDK is not installed.") from error

    try:
        event = stripe.Webhook.construct_event(
            payload=raw_body, sig_header=signature_header, secret=secret
        )
    except (stripe.SignatureVerificationError, ValueError) as error:
        # Narrow on purpose. Catching everything here once turned an
        # unrelated AttributeError into "rejected: object", which reads as a
        # signature problem and hides the actual bug. Anything else is ours
        # and should surface as a 500 with a traceback.
        raise SignatureError(str(error)) from error

    # construct_event returns a StripeObject, whose attribute access is
    # routed through __getattr__ — so .get() raises AttributeError instead of
    # behaving like a dict. Convert once, here, and let every handler below
    # work with plain dicts.
    return json.loads(str(event))


@extend_schema(exclude=True)
class StripeBillingWebhookAPIView(APIView):

    authentication_classes = []
    permission_classes = []

    def post(self, request):
        try:
            event = verify_stripe_signature(
                raw_body=request.body,
                signature_header=request.META.get(
                    "HTTP_STRIPE_SIGNATURE", ""
                ),
                secret=getattr(
                    settings, "STRIPE_BILLING_WEBHOOK_SECRET", ""
                ),
            )
        except SignatureError as error:
            logger.warning("rejected Stripe billing webhook: %s", error)

            return ApiResponse.error(
                message=str(error), code=INVALID_SIGNATURE
            )

        event_type = event.get("type", "")

        if event_type not in HANDLED:
            # Acknowledged, not refused. A 400 here would have Stripe retry
            # an event we will never care about until it disables the
            # endpoint — taking the events we *do* care about with it.
            return Response({"received": True, "handled": False})

        handled = self._apply(event_type, event)

        return Response({"received": True, "handled": handled})

    # --- handlers ---------------------------------------------------------

    def _apply(self, event_type, event):
        obj = (event.get("data") or {}).get("object") or {}
        subscription = self._locate(obj)

        if subscription is None:
            logger.info(
                "Stripe billing event %s references no known subscription",
                event_type,
            )

            return False

        if event_type in ("invoice.paid", "invoice.payment_succeeded"):
            return self._set_status(
                subscription, SubscriptionStatus.ACTIVE, "active"
            )

        if event_type == "invoice.payment_failed":
            # PAST_DUE, not CANCELLED. A failed charge is a card problem the
            # customer can fix, and cutting off a paying business the first
            # time a card expires would be the wrong end of the trade.
            return self._set_status(
                subscription, SubscriptionStatus.PAST_DUE, "past_due"
            )

        if event_type == "customer.subscription.deleted":
            return self._set_status(
                subscription, SubscriptionStatus.CANCELLED, "canceled"
            )

        if event_type == "customer.subscription.updated":
            mapped = swayp_status(obj.get("status", ""))

            if mapped is None:
                return False

            return self._set_status(
                subscription, mapped, obj.get("status", "")
            )

        return False

    def _locate(self, obj):
        reference = obj.get("subscription") or obj.get("id") or ""

        if not reference:
            return None

        return Subscription.objects.filter(
            provider_subscription_id=reference
        ).first()

    def _set_status(self, subscription, new_status, provider_status):
        if subscription.status == SubscriptionStatus.CANCELLED:
            # A cancelled subscription stays cancelled. Out-of-order delivery
            # must not resurrect one because a late invoice.paid arrived.
            subscription.provider_status = provider_status
            subscription.save(
                update_fields=["provider_status", "updated_at"]
            )

            return False

        subscription.status = new_status
        subscription.provider_status = provider_status
        subscription.save(
            update_fields=["status", "provider_status", "updated_at"]
        )

        return True
