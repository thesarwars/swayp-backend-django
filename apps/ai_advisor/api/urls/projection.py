from django.urls import path

from apps.ai_advisor.api.views.projection import BalanceProjectionAPIView

urlpatterns = [
    path(
        "/balance-projection",
        BalanceProjectionAPIView.as_view(),
        name="ai-balance-projection",
    ),
]
