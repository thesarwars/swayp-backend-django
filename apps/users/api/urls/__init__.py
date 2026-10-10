from django.urls import path

from apps.users.api.views.onboarding import (
    OnboardingAPIView,
    OnboardingSkipBankAPIView,
)
from apps.users.api.views.phone_change import (
    PhoneChangeRequestAPIView,
    PhoneChangeVerifyAPIView,
)
from apps.users.api.views.profile import ProfileAPIView

urlpatterns = [
    path("/profile", ProfileAPIView.as_view(), name="user-profile"),
    path(
        "/profile/phone",
        PhoneChangeRequestAPIView.as_view(),
        name="user-profile-phone",
    ),
    path(
        "/profile/phone/verify",
        PhoneChangeVerifyAPIView.as_view(),
        name="user-profile-phone-verify",
    ),
    path(
        "/onboarding",
        OnboardingAPIView.as_view(),
        name="user-onboarding",
    ),
    path(
        "/onboarding/skip-bank",
        OnboardingSkipBankAPIView.as_view(),
        name="user-onboarding-skip-bank",
    ),
]
