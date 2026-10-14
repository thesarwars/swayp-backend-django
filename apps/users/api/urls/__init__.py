from django.urls import path

from apps.users.api.views.onboarding import (
    OnboardingAPIView,
    OnboardingSkipBankAPIView,
)
from apps.users.api.views.phone_change import (
    PhoneChangeRequestAPIView,
    PhoneChangeVerifyAPIView,
)
from apps.users.api.views.password import ChangePasswordAPIView
from apps.users.api.views.profile import ProfileAPIView
from apps.users.api.views.profile_picture import ProfilePictureAPIView

urlpatterns = [
    path("/profile", ProfileAPIView.as_view(), name="user-profile"),
    path(
        "/profile/picture",
        ProfilePictureAPIView.as_view(),
        name="user-profile-picture",
    ),
    path(
        "/password",
        ChangePasswordAPIView.as_view(),
        name="user-change-password",
    ),
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
