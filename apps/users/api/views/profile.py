"""The account's own profile (settings screen)."""

from drf_spectacular.utils import extend_schema

from apps.common.base_views import BaseAPIView
from apps.common.responses import ApiResponse
from apps.teams.access import AccountScopedMixin
from apps.common.swagger import BAD_REQUEST_RESPONSE, UNAUTHORIZED_RESPONSE
from apps.users.api.serializers.profile import (
    ProfileResponseSerializer,
    ProfileSerializer,
    ProfileUpdateSerializer,
)
from apps.users.services.profile_service import ProfileService


class ProfileAPIView(AccountScopedMixin, BaseAPIView):

    service_class = ProfileService

    @extend_schema(
        tags=["Users"],
        summary="Account profile",
        description=(
            "Read the account's own profile. business_name and poc_name are "
            "null on an individual account."
        ),
        responses={
            200: ProfileResponseSerializer,
            401: UNAUTHORIZED_RESPONSE,
        },
    )
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

    @extend_schema(
        tags=["Users"],
        summary="Update account profile",
        description=(
            "Partial update: send only what changed; an empty body is a 400. "
            "Answers with the full updated profile, the same body as GET, so "
            "no refetch is needed. Email and phone are read-only here — "
            "phone changes go through users/profile/phone."
        ),
        request=ProfileUpdateSerializer,
        responses={
            200: ProfileResponseSerializer,
            400: BAD_REQUEST_RESPONSE,
            401: UNAUTHORIZED_RESPONSE,
        },
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
