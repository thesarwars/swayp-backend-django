from django.urls import path

from apps.authentication.api.views.mfa import (
    MFAConfirmAPIView,
    MFADisableAPIView,
    MFALoginAPIView,
    MFARecoveryCodesAPIView,
    MFASetupAPIView,
    MFAStatusAPIView,
)

urlpatterns = [
    path("/login/mfa", MFALoginAPIView.as_view(), name="login-mfa"),
    path("/mfa", MFAStatusAPIView.as_view(), name="mfa-status"),
    path("/mfa/setup", MFASetupAPIView.as_view(), name="mfa-setup"),
    path("/mfa/confirm", MFAConfirmAPIView.as_view(), name="mfa-confirm"),
    path("/mfa/disable", MFADisableAPIView.as_view(), name="mfa-disable"),
    path(
        "/mfa/recovery-codes",
        MFARecoveryCodesAPIView.as_view(),
        name="mfa-recovery-codes",
    ),
]
