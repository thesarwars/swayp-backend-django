from django.urls import path

from apps.billing.api.views.webhook import StripeBillingWebhookAPIView
from apps.billing.api.views.billing import (
    AddOnAPIView,
    AllowanceAPIView,
    FeeChargeListAPIView,
    InvoicePreviewAPIView,
    PaymentMethodAPIView,
    PaymentMethodSetupAPIView,
    PlanListAPIView,
    SubscriptionAPIView,
    SubscriptionResumeAPIView,
)

urlpatterns = [
    path("/plans", PlanListAPIView.as_view(), name="billing-plan-list"),
    path(
        "/subscription/resume",
        SubscriptionResumeAPIView.as_view(),
        name="billing-subscription-resume",
    ),
    path(
        "/subscription",
        SubscriptionAPIView.as_view(),
        name="billing-subscription",
    ),
    path(
        "/allowances",
        AllowanceAPIView.as_view(),
        name="billing-allowances",
    ),
    path("/addons", AddOnAPIView.as_view(), name="billing-addons"),
    path("/invoice", InvoicePreviewAPIView.as_view(), name="billing-invoice"),
    path("/fees", FeeChargeListAPIView.as_view(), name="billing-fees"),
    path(
        "/payment-method",
        PaymentMethodAPIView.as_view(),
        name="billing-payment-method",
    ),
    path(
        "/payment-method/setup",
        PaymentMethodSetupAPIView.as_view(),
        name="billing-payment-method-setup",
    ),
]
