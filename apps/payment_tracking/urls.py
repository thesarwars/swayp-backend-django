from django.urls import path

from .views import PaymentTrackingAPIView

app_name = "payment_tracking"

urlpatterns = [
    path(
        "",
        PaymentTrackingAPIView.as_view(),
        name="payment-tracking",
    ),
]