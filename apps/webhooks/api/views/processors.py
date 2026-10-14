"""One view per processor (E6-S8).

Each only differs by which secret and signature header it uses; the handling
is shared so a new processor cannot accidentally get different semantics.
"""

from drf_spectacular.utils import extend_schema

from apps.payments.services.webhook_service import SignatureError
from apps.webhooks.base import WebhookAPIView


@extend_schema(tags=["Webhooks"], summary="Stripe callback", request=None, auth=[], responses={200: None})
class StripeWebhookAPIView(WebhookAPIView):
    processor = "STRIPE"
    signature_header = "HTTP_STRIPE_SIGNATURE"


@extend_schema(tags=["Webhooks"], summary="Lob callback", request=None, auth=[], responses={200: None})
class LobWebhookAPIView(WebhookAPIView):
    processor = "LOB"
    signature_header = "HTTP_LOB_SIGNATURE"


@extend_schema(tags=["Webhooks"], summary="Plaid callback", request=None, auth=[], responses={200: None})
class PlaidWebhookAPIView(WebhookAPIView):
    """Plaid fits none of the shared assumptions, so it overrides all three.

    * **Signature.** Plaid sends an ES256 JWT, not an HMAC of the body, so
      verification is delegated to the provider that knows the scheme.
    * **Event id.** Plaid callbacks carry no id of any kind — only
      ``webhook_type``, ``webhook_code`` and ``item_id`` — so the shared
      "payload has no event id" check rejected every one of them.
    * **Meaning.** They are about data readiness, not payment state, and the
      default handler looks for a payment reference that is never there.
    """

    processor = "PLAID"
    signature_header = "HTTP_PLAID_VERIFICATION"

    def verify(self, request, raw):
        from integrations.factory import get_bank_data_provider

        try:
            get_bank_data_provider().verify_webhook(
                raw_body=raw,
                header_value=request.META.get(self.signature_header, ""),
            )
        except Exception as exc:
            # Narrowed to the shared type the base view already handles, so
            # an unverified callback is refused the same way for every
            # processor and still writes no row.
            raise SignatureError(str(exc)) from exc

    def event_id(self, payload):
        """Synthesised, because Plaid does not send one.

        The body hash is the identity: Plaid's retries resend the same bytes,
        which is exactly what should dedupe, while a genuinely different
        callback hashes differently. Keyed on the item too so the id reads as
        something in a log rather than as a bare digest.
        """
        import hashlib
        import json

        digest = hashlib.sha256(
            json.dumps(payload, sort_keys=True).encode()
        ).hexdigest()

        return (
            f"{payload.get('item_id', 'no-item')}:"
            f"{payload.get('webhook_code', 'no-code')}:{digest[:16]}"
        )

    def event_type(self, payload):
        return payload.get("webhook_code") or ""

    def handle(self, payload):
        """Record for dedupe and audit, then act on it.

        The recording is reused from WebhookService because the dedupe
        constraint and the event row are worth having for any processor; only
        what the event *means* is Plaid's own.
        """
        from apps.banking.services.plaid_webhook_service import (
            PlaidWebhookService,
        )
        from apps.payments.services.webhook_service import WebhookService

        _, is_new = WebhookService().record(
            processor=self.processor,
            event_id=self.event_id(payload),
            event_type=self.event_type(payload),
            payload=payload,
        )

        if not is_new:
            return "duplicate"

        return PlaidWebhookService().handle(payload)


@extend_schema(tags=["Webhooks"], summary="Mock processor callback", request=None, auth=[], responses={200: None})
class MockWebhookAPIView(WebhookAPIView):
    processor = "MOCK"
    signature_header = "HTTP_X_SWAYP_SIGNATURE"
