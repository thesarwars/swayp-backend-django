from django.urls import path

from .views import PaymentHistoryAPIView

app_name = "payments"

urlpatterns = [
    path(
        "history/",
        PaymentHistoryAPIView.as_view(),
        name="payment-history",
    ),
]