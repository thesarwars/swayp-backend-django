

from django.contrib import admin
from django.urls import path,include

from apps.billing.api.views.webhook import StripeBillingWebhookAPIView
from apps.common.api_health import LivenessAPIView, ReadinessAPIView
from drf_spectacular.views import (
    SpectacularAPIView,
    SpectacularSwaggerView,
    SpectacularRedocView,
)

urlpatterns = [
    # Probes, versionless and unauthenticated — a load balancer has
    # no token and should not need to know the API version.
    path("healthz", LivenessAPIView.as_view(), name="healthz"),
    path("readyz", ReadinessAPIView.as_view(), name="readyz"),

    path("admin/", admin.site.urls),

      path(
        "api/schema/",
        SpectacularAPIView.as_view(),
        name="schema",
    ),

    path(
        "api/docs/",
        SpectacularSwaggerView.as_view(
            url_name="schema"
        ),
        name="swagger-ui",
    ),

    path(
        "api/redoc/",
        SpectacularRedocView.as_view(
            url_name="schema"
        ),
        name="redoc",
    ),
    path("api/v1/", include("api.v1.urls")),
    # Versionless: a processor-registered URL must never move with an
    # API version (E6-S8).
    path("webhooks/", include("apps.webhooks.api.urls")),
    # Stripe Billing signs differently from the payment rails and is about
    # subscriptions rather than money movement, so it gets its own
    # versionless endpoint (E9-S1).
    path(
        "webhooks/stripe/billing/",
        StripeBillingWebhookAPIView.as_view(),
        name="webhook-stripe-billing",
    ),
]
