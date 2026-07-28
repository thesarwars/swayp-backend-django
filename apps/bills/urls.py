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
from apps.bills.views.next_due import NextDueAPIView
from apps.bills.views.summary import BillSummaryAPIView

urlpatterns = [
    path("", BillListAPIView.as_view(), name="bill-list"),
    path("create/", BillCreateAPIView.as_view(), name="bill-create"),
    path("summary/", BillSummaryAPIView.as_view(), name="bill-summary"),
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
]
