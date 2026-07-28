from django.urls import path

from apps.ai_advisor.api.views.cash_context import CashContextAPIView

urlpatterns = [
    path(
        "cash-context/",
        CashContextAPIView.as_view(),
        name="ai-cash-context",
    ),
]
