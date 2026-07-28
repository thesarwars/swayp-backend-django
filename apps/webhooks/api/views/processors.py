"""One view per processor (E6-S8).

Each only differs by which secret and signature header it uses; the handling
is shared so a new processor cannot accidentally get different semantics.
"""

from drf_spectacular.utils import extend_schema

from apps.webhooks.base import WebhookAPIView


@extend_schema(tags=["Webhooks"], summary="Moov callback")
class MoovWebhookAPIView(WebhookAPIView):
    processor = "MOOV"
    signature_header = "HTTP_X_MOOV_SIGNATURE"


@extend_schema(tags=["Webhooks"], summary="Stripe callback")
class StripeWebhookAPIView(WebhookAPIView):
    processor = "STRIPE"
    signature_header = "HTTP_STRIPE_SIGNATURE"


@extend_schema(tags=["Webhooks"], summary="Lob callback")
class LobWebhookAPIView(WebhookAPIView):
    processor = "LOB"
    signature_header = "HTTP_LOB_SIGNATURE"


@extend_schema(tags=["Webhooks"], summary="Plaid callback")
class PlaidWebhookAPIView(WebhookAPIView):
    processor = "PLAID"
    signature_header = "HTTP_PLAID_VERIFICATION"


@extend_schema(tags=["Webhooks"], summary="Mock processor callback")
class MockWebhookAPIView(WebhookAPIView):
    processor = "MOCK"
    signature_header = "HTTP_X_SWAYP_SIGNATURE"
