from django.urls import path

from apps.banking.api.views.banking import (
    BankAccountListAPIView,
    BankConnectionDetailAPIView,
    BankConnectionListAPIView,
    LinkExchangeAPIView,
    LinkTokenAPIView,
    OnboardingSummaryAPIView,
    ScanCandidateListAPIView,
    ScanDetailAPIView,
    ScanImportAPIView,
    ScanStartAPIView,
)

urlpatterns = [
    path("/link/token", LinkTokenAPIView.as_view(), name="banking-link-token"),
    path(
        "/link/exchange",
        LinkExchangeAPIView.as_view(),
        name="banking-link-exchange",
    ),
    path(
        "/connections",
        BankConnectionListAPIView.as_view(),
        name="banking-connection-list",
    ),
    path(
        "/connections/<uuid:connection_id>",
        BankConnectionDetailAPIView.as_view(),
        name="banking-connection-detail",
    ),
    path(
        "/accounts",
        BankAccountListAPIView.as_view(),
        name="banking-account-list",
    ),
    path("/scans", ScanStartAPIView.as_view(), name="banking-scan-start"),
    path(
        "/scans/<uuid:scan_id>",
        ScanDetailAPIView.as_view(),
        name="banking-scan-detail",
    ),
    path(
        "/scans/<uuid:scan_id>/candidates",
        ScanCandidateListAPIView.as_view(),
        name="banking-scan-candidates",
    ),
    path(
        "/scans/<uuid:scan_id>/import",
        ScanImportAPIView.as_view(),
        name="banking-scan-import",
    ),
    path(
        "/onboarding-summary",
        OnboardingSummaryAPIView.as_view(),
        name="banking-onboarding-summary",
    ),
]
