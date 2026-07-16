from django.urls import path

from apps.authentication.api.views.otp import ResendOTPView

urlpatterns = [
    path(
        "resend-otp/",
        ResendOTPView.as_view(),
        name="resend-otp",
    ),
]
