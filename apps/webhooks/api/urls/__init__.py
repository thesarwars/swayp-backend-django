from django.urls import path

from apps.webhooks.api.views.processors import (
    LobWebhookAPIView,
    MockWebhookAPIView,
    MoovWebhookAPIView,
    PlaidWebhookAPIView,
    StripeWebhookAPIView,
)

# Mounted versionless at /webhooks/ — a processor-registered URL must never
# move with an API version.
urlpatterns = [
    path("/moov", MoovWebhookAPIView.as_view(), name="webhook-moov"),
    path("/stripe", StripeWebhookAPIView.as_view(), name="webhook-stripe"),
    path("/lob", LobWebhookAPIView.as_view(), name="webhook-lob"),
    path("/plaid", PlaidWebhookAPIView.as_view(), name="webhook-plaid"),
    path("/mock", MockWebhookAPIView.as_view(), name="webhook-mock"),
]
