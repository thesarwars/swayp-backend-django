from django.urls import path

from apps.authentication.api.views.otp import (
    ResendOTPView,
    VerifyOTPView,
)

urlpatterns = [
    # The single verify route. It replaces the pair that used to live in
    # user_registration.py and user_login.py: an emailed code says nothing
    # about which flow issued it, so making the client pick the matching
    # endpoint was asking it to know something it cannot see.
    path(
        "/verify-otp",
        VerifyOTPView.as_view(),
        name="verify-otp",
    ),

    path(
        "/resend-otp",
        ResendOTPView.as_view(),
        name="resend-otp",
    ),
]
