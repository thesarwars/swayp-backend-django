from django.urls import path

from apps.authentication.api.views.user_login import LoginView

# /login/verify is gone. The login code is verified at /auth/verify-otp with
# the registration one (urls/otp.py); /login/phone/verify stays, because it is
# keyed by phone number rather than email and has nothing to merge with.
urlpatterns = [
    path(
        "/login",
        LoginView.as_view(),
        name="login",
    ),
]
