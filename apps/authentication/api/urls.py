from django.urls import path

from apps.authentication.api.views import (
    RegisterView, VerifyOTPView, LoginView
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
]