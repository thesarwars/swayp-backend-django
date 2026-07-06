from django.urls import path

from .views import WalletSummaryAPIView

app_name = "wallet"

urlpatterns = [
    path(
        "summary/",
        WalletSummaryAPIView.as_view(),
        name="wallet-summary",
    ),
]