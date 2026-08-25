"""Base view for processor callbacks (E6-S8).

Unauthenticated by necessity — a processor has no Swayp token. Trust comes
from the signature over the raw body instead, so:

- authentication and permissions are off,
- the signature is verified against ``request.body`` before anything is
  parsed, because re-serializing parsed JSON changes bytes and would never
  match,
- the response acknowledges quickly; a processor that does not get a 200
  retries, and duplicate delivery is handled by the dedupe constraint.
"""

import json
import logging

from django.conf import settings
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.payments.services.webhook_service import (
    SignatureError,
    WebhookService,
    verify_signature,
)

logger = logging.getLogger(__name__)


class WebhookAPIView(APIView):

    authentication_classes = []
    permission_classes = []

    #: Set by each subclass.
    processor = "MOCK"
    signature_header = "HTTP_X_SWAYP_SIGNATURE"

    def secret(self):
        return getattr(settings, "WEBHOOK_SECRETS", {}).get(self.processor)

    def event_id(self, payload):
        return payload.get("id") or payload.get("event_id") or ""

    def event_type(self, payload):
        return payload.get("type") or payload.get("event_type") or ""

    def verify(self, request, raw):
        """Prove the sender. Overridable, because not everyone signs alike.

        The shared default is HMAC-SHA256 over the raw body, which is what the
        payment processors use. Sharing it was meant to stop a new processor
        quietly getting weaker semantics — but a processor that signs
        differently cannot be made to fit by wishing, and forcing it here
        would mean rejecting every one of its callbacks. Plaid is one: it
        sends a signed JWT, not an HMAC.
        """
        verify_signature(
            processor=self.processor,
            raw_body=raw,
            signature=request.META.get(self.signature_header, ""),
            secret=self.secret(),
        )

    def handle(self, payload):
        """What the event means. Overridable for the same reason.

        The default routes to payment state, which is what a processor
        callback is. Plaid's callbacks are about data readiness and mean
        nothing to a Payment.
        """
        return WebhookService().handle(
            processor=self.processor,
            event_id=self.event_id(payload),
            event_type=self.event_type(payload),
            payload=payload,
        )

    def post(self, request):
        raw = request.body

        try:
            self.verify(request, raw)
        except SignatureError as error:
            logger.warning(
                "rejected %s webhook: %s", self.processor, error
            )
            # No event row is written for an unverified payload.
            return Response(
                {"detail": str(error)},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            payload = json.loads(raw or b"{}")
        except ValueError:
            return Response(
                {"detail": "Malformed JSON payload."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        event_id = self.event_id(payload)

        if not event_id:
            return Response(
                {"detail": "Payload has no event id."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        return Response({"received": True, "result": self.handle(payload)})
