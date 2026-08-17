from django.urls import path

from apps.authentication.api.views.user_registration import RegisterView

# Verification lives at /auth/verify-otp, registered in urls/otp.py alongside
# resend — it serves the login code too now, so it is no longer a registration
# route.
urlpatterns = [
    path(
        "/register",
        RegisterView.as_view(),
        name="register",
    ),
]
