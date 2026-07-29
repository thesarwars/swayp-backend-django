from django.urls import path

from apps.reports.api.views.report import (
    Form1099ReportAPIView,
    PaymentsReportAPIView,
)

urlpatterns = [
    # The 1099 route comes first so "1099" is never read as anything else.
    path(
        "1099/",
        Form1099ReportAPIView.as_view(),
        name="reports-1099",
    ),
    path(
        "",
        PaymentsReportAPIView.as_view(),
        name="reports-payments",
    ),
]
