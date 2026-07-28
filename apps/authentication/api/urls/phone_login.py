from django.urls import path

from apps.authentication.api.views.phone_login import (
    PhoneLoginRequestView,
    PhoneLoginVerifyView,
)

urlpatterns = [
    path(
        "login/phone/request/",
        PhoneLoginRequestView.as_view(),
        name="login-phone-request",
    ),
    path(
        "login/phone/verify/",
        PhoneLoginVerifyView.as_view(),
        name="login-phone-verify",
    ),
]
