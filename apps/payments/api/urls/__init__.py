from django.urls import path

from apps.payments.api.views.payment import (
    BatchCancelAPIView,
    BatchConfirmAPIView,
    BatchStatusAPIView,
    PaymentCancelAPIView,
    PaymentConfirmAPIView,
    PaymentCreateAPIView,
    PaymentDetailAPIView,
    PaymentFailureAPIView,
    PaymentReceiptPDFAPIView,
    PaymentResolveAPIView,
    PaymentStatusAPIView,
)
from apps.payments.api.views.quote import PaymentQuoteAPIView
from apps.payments.views import (
    PaymentFailedAPIView,
    PaymentHistoryAPIView,
    PaymentProcessingAPIView,
    PaymentSuccessAPIView,
)

app_name = "payments"

urlpatterns = [
    path("", PaymentCreateAPIView.as_view(), name="payment-create"),
    path("/quote", PaymentQuoteAPIView.as_view(), name="payment-quote"),
    path(
        "/history",
        PaymentHistoryAPIView.as_view(),
        name="payment-history",
    ),
    # Batch routes come before <uuid:payment_id> so "batches" is never read
    # as a payment id.
    path(
        "/batches/<uuid:batch_id>/confirm",
        BatchConfirmAPIView.as_view(),
        name="payment-batch-confirm",
    ),
    path(
        "/batches/<uuid:batch_id>/status",
        BatchStatusAPIView.as_view(),
        name="payment-batch-status",
    ),
    path(
        "/batches/<uuid:batch_id>/cancel",
        BatchCancelAPIView.as_view(),
        name="payment-batch-cancel",
    ),
    path(
        "/<uuid:payment_id>",
        PaymentDetailAPIView.as_view(),
        name="payment-detail",
    ),
    path(
        "/<uuid:payment_id>/confirm",
        PaymentConfirmAPIView.as_view(),
        name="payment-confirm",
    ),
    path(
        "/<uuid:payment_id>/status",
        PaymentStatusAPIView.as_view(),
        name="payment-status",
    ),
    path(
        "/<uuid:payment_id>/cancel",
        PaymentCancelAPIView.as_view(),
        name="payment-cancel",
    ),
    path(
        "/<uuid:payment_id>/receipt.pdf",
        PaymentReceiptPDFAPIView.as_view(),
        name="payment-receipt-pdf",
    ),
    path(
        "/<uuid:payment_id>/failure",
        PaymentFailureAPIView.as_view(),
        name="payment-failure",
    ),
    path(
        "/<uuid:payment_id>/resolve",
        PaymentResolveAPIView.as_view(),
        name="payment-resolve",
    ),
    # Deprecated (E6-S10). Staff-only; status is driven by the processor
    # and its webhooks. Kept routed so the deprecation is visible in the
    # schema before removal.
    path(
        "/<uuid:payment_id>/processing",
        PaymentProcessingAPIView.as_view(),
        name="payment-processing",
    ),
    path(
        "/<uuid:payment_id>/successful",
        PaymentSuccessAPIView.as_view(),
        name="payment-successful",
    ),
    path(
        "/<uuid:payment_id>/failed",
        PaymentFailedAPIView.as_view(),
        name="payment-failed",
    ),
]
