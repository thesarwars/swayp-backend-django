"""Where a signup got to (E2-S6)."""

from drf_spectacular.utils import extend_schema

from apps.common.base_views import BaseAPIView
from apps.common.responses import ApiResponse
from apps.teams.access import AccountScopedMixin
from apps.teams.permissions import MANAGE_BANKS
from apps.users.api.serializers.onboarding import (
    OnboardingStateResponseSerializer,
)
from apps.users.services.onboarding_service import OnboardingService


@extend_schema(
    tags=["Users"],
    summary="Onboarding progress",
    description=(
        "Which onboarding steps are done and which to resume at. Derived "
        "from the real data each step creates, so it cannot drift from "
        "reality — connecting a bank from Settings completes step 4 too. "
        "current_step is null once nothing is outstanding."
    ),
    responses={200: OnboardingStateResponseSerializer},
)
class OnboardingAPIView(AccountScopedMixin, BaseAPIView):

    service_class = OnboardingService

    def get(self, request):
        return ApiResponse.success(
            data=self.service.state(self.account(request)),
            message="Onboarding state fetched successfully.",
        )


@extend_schema(
    tags=["Users"],
    summary="Skip the bank step",
    request=None,
    description=(
        "Records the \"Skip for now\" choice on step 4. The only part of "
        "progress that cannot be derived, because declining a step leaves no "
        "trace in the data. Answers with the updated progress, the same "
        "body as GET users/onboarding."
    ),
    responses={200: OnboardingStateResponseSerializer},
)
class OnboardingSkipBankAPIView(AccountScopedMixin, BaseAPIView):

    service_class = OnboardingService
    required_capability = MANAGE_BANKS

    def post(self, request):
        return ApiResponse.success(
            data=self.service.skip_bank(self.account(request)),
            message="Bank connection skipped.",
        )
