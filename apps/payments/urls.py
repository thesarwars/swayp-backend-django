from django.urls import path

from .views import (
    PaymentHistoryAPIView,
    CreatePaymentAPIView,
    PaymentProcessingAPIView,
    PaymentSuccessAPIView,
    PaymentFailedAPIView,
)
app_name = "payments"

urlpatterns = [
    path(
        "",
        CreatePaymentAPIView.as_view(),
        name="payment-create",
    ),
    path(
        "history/",
        PaymentHistoryAPIView.as_view(),
        name="payment-history",
    ),

    path(
        "<uuid:payment_id>/processing/",
        PaymentProcessingAPIView.as_view(),
        name="payment-processing",
    ),
    path(
        "<uuid:payment_id>/successful/",
        PaymentSuccessAPIView.as_view(),
        name="payment-successful",
    ),

    path(
        "<uuid:payment_id>/failed/",
        PaymentFailedAPIView.as_view(),
        name="payment-failed",
    ),
]