from django.urls import path

from apps.bill_categories.views.bill import BillCreateAPIView, BillDetailAPIView, BillListAPIView, BillUpdateAPIView
from apps.bill_categories.views.bill_occurrence import MarkBillOccurrencePaidAPIView, UpcomingBillOccurrenceAPIView
from apps.bill_categories.views.next_due import NextDueAPIView
from apps.bill_categories.views.summary import BillSummaryAPIView

urlpatterns = [
    path("create/",BillCreateAPIView.as_view(),name="bill-create"),
    path("",BillListAPIView.as_view(),name="bill-list"),
    path("<uuid:bill_id>/details/",BillDetailAPIView.as_view(),name="bill-detail"),
    path("<uuid:bill_id>/update/",BillUpdateAPIView.as_view(),name="bill-update"),
    path("occurrences/upcoming/",UpcomingBillOccurrenceAPIView.as_view(),name="upcoming-bill-occurrences"),
    path(
    "bill-occurrences/<uuid:occurrence_id>/pay/",
    MarkBillOccurrencePaidAPIView.as_view(),
    name="mark-bill-occurrence-paid",
),
    path(
    "bills/summary/",
    BillSummaryAPIView.as_view(),
    name="bill-summary",
),
    path("bills/next-due/",NextDueAPIView.as_view(),name="bill-next-due"),

]