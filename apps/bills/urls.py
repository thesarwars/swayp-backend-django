from django.urls import path

from apps.bills.views.bill import (
    BillCreateAPIView,
    BillDetailAPIView,
    BillListAPIView,
    BillUpdateAPIView,
)
from apps.bills.views.bill_occurrence import (
    MarkBillOccurrencePaidAPIView,
    UpcomingBillOccurrenceAPIView,
)
from apps.bills.views.invoice import BillInvoiceAPIView
from apps.bills.views.next_due import NextDueAPIView
from apps.bills.views.occurrences import BillOccurrenceListAPIView
from apps.bills.views.payments import BillPaymentHistoryAPIView
from apps.bills.views.qr import BillQRDecodeAPIView
from apps.bills.views.summary import BillSummaryAPIView

urlpatterns = [
    path("", BillListAPIView.as_view(), name="bill-list"),
    path("create/", BillCreateAPIView.as_view(), name="bill-create"),
    path("summary/", BillSummaryAPIView.as_view(), name="bill-summary"),
    path(
        "occurrences/",
        BillOccurrenceListAPIView.as_view(),
        name="bill-occurrence-list",
    ),
    path(
        "qr/decode/",
        BillQRDecodeAPIView.as_view(),
        name="bill-qr-decode",
    ),
    path("next-due/", NextDueAPIView.as_view(), name="bill-next-due"),
    path(
        "occurrences/upcoming/",
        UpcomingBillOccurrenceAPIView.as_view(),
        name="upcoming-bill-occurrences",
    ),
    path(
        "occurrences/<uuid:occurrence_id>/pay/",
        MarkBillOccurrencePaidAPIView.as_view(),
        name="mark-bill-occurrence-paid",
    ),
    path(
        "<uuid:bill_id>/details/",
        BillDetailAPIView.as_view(),
        name="bill-detail",
    ),
    path(
        "<uuid:bill_id>/update/",
        BillUpdateAPIView.as_view(),
        name="bill-update",
    ),
    path(
        "<uuid:bill_id>/payments/",
        BillPaymentHistoryAPIView.as_view(),
        name="bill-payment-history",
    ),
    path(
        "<uuid:bill_id>/invoice/",
        BillInvoiceAPIView.as_view(),
        name="bill-invoice",
    ),
]
