from django.urls import path

from apps.authentication.api.views import (
    RegisterView, VerifyOTPView, LoginView, LoginVerifyOTPView, ResendOTPView
)

urlpatterns = [
    path(
        "register/",
        RegisterView.as_view(),
        name="register",
    ),

    path(
        "verify-otp/",
        VerifyOTPView.as_view(),
        name="verify-otp",
    ),

    path("login/", LoginView.as_view()),

    path(
        "login/verify/",
        LoginVerifyOTPView.as_view(),
    ),
    path(
    "resend-otp/",
    ResendOTPView.as_view(),
    name="resend-otp",
),
]