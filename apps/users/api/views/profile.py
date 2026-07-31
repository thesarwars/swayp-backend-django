"""The account's own profile (settings screen)."""

from drf_spectacular.utils import extend_schema

from apps.common.base_views import BaseAPIView
from apps.common.responses import ApiResponse
from apps.teams.access import AccountScopedMixin
from apps.users.api.serializers.profile import (
    ProfileSerializer,
    ProfileUpdateSerializer,
)
from apps.users.services.profile_service import ProfileService


@extend_schema(
    tags=["Users"],
    summary="Account profile",
    description=(
        "Read or update the account's own profile. business_name and "
        "poc_name are null on an individual account. Email and phone are "
        "read-only here — both are login identifiers verified by OTP."
    ),
    responses={200: ProfileSerializer},
)
class ProfileAPIView(AccountScopedMixin, BaseAPIView):

    service_class = ProfileService

    def get(self, request):
        # The account, not request.user: a team member opening settings is
        # looking at the business they work for, and the billing address on
        # the invoice belongs to that account rather than to them.
        return ApiResponse.success(
            data=ProfileSerializer(
                self.service.read(self.account(request))
            ).data,
            message="Profile fetched successfully.",
        )

    def patch(self, request):
        serializer = ProfileUpdateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        updated = self.service.update(
            self.account(request), serializer.validated_data
        )

        return ApiResponse.success(
            data=ProfileSerializer(updated).data,
            message="Profile updated.",
        )
