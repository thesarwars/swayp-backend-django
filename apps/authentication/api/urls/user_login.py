from django.urls import path

from apps.authentication.api.views.user_login import (
    LoginVerifyOTPView,
    LoginView,
)

urlpatterns = [
    path(
        "login/",
        LoginView.as_view(),
        name="login",
    ),

    path(
        "login/verify/",
        LoginVerifyOTPView.as_view(),
        name="login-verify",
    ),
]
