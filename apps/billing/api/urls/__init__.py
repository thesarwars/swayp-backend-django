from django.urls import path

from apps.billing.api.views.webhook import StripeBillingWebhookAPIView
from apps.billing.api.views.billing import (
    AddOnAPIView,
    AllowanceAPIView,
    FeeChargeListAPIView,
    InvoicePreviewAPIView,
    PaymentMethodSetupAPIView,
    PlanListAPIView,
    SubscriptionAPIView,
)

urlpatterns = [
    path("/plans", PlanListAPIView.as_view(), name="billing-plan-list"),
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
        "/payment-method/setup",
        PaymentMethodSetupAPIView.as_view(),
        name="billing-payment-method-setup",
    ),
]
