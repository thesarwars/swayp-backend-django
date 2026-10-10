"""Adding or changing the phone number from settings (AUTH-10)."""

from drf_spectacular.utils import extend_schema

from apps.common.base_views import BaseAPIView
from apps.common.responses import ApiResponse
from apps.common.swagger import (
    BAD_REQUEST_RESPONSE,
    UNAUTHORIZED_RESPONSE,
)
from apps.users.api.serializers.phone_change import (
    PhoneChangeRequestResponseSerializer,
    PhoneChangeRequestSerializer,
    PhoneChangeVerifySerializer,
)
from apps.users.api.serializers.profile import (
    ProfileResponseSerializer,
    ProfileSerializer,
)
from apps.users.services.phone_change_service import PhoneChangeService
from apps.users.services.profile_service import ProfileService


@extend_schema(
    tags=["Users"],
    summary="Request a phone-change code",
    description=(
        "Starts adding or changing the signed-in user's phone number. A "
        "PHONE_CHANGE code is emailed to the account's address (SMS is not "
        "available this release) and is valid only for the number sent "
        "here. Throttled like resend-otp: 429 with Retry-After."
    ),
    request=PhoneChangeRequestSerializer,
    responses={
        200: PhoneChangeRequestResponseSerializer,
        400: BAD_REQUEST_RESPONSE,
        401: UNAUTHORIZED_RESPONSE,
    },
)
class PhoneChangeRequestAPIView(BaseAPIView):

    service_class = PhoneChangeService

    def post(self, request):
        serializer = PhoneChangeRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        # request.user, not the team account: the number signs *this person*
        # in, so it belongs to them rather than to the business they work for.
        data = self.service.request(
            user=request.user,
            phone_number=serializer.validated_data["phone_number"],
        )

        return ApiResponse.success(
            data=data,
            message=f"A code has been sent to {data['email']}.",
        )


@extend_schema(
    tags=["Users"],
    summary="Confirm a phone change",
    description=(
        "Spends the PHONE_CHANGE code and sets the number. phone_number must "
        "be the one the code was requested for. Returns the updated profile."
    ),
    request=PhoneChangeVerifySerializer,
    responses={
        200: ProfileResponseSerializer,
        400: BAD_REQUEST_RESPONSE,
        401: UNAUTHORIZED_RESPONSE,
    },
)
class PhoneChangeVerifyAPIView(BaseAPIView):

    service_class = PhoneChangeService

    def post(self, request):
        serializer = PhoneChangeVerifySerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        user = self.service.verify(
            user=request.user,
            phone_number=serializer.validated_data["phone_number"],
            otp=serializer.validated_data["otp"],
        )

        return ApiResponse.success(
            data=ProfileSerializer(ProfileService().read(user)).data,
            message="Phone number updated.",
        )
