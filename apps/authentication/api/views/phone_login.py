from django.contrib.auth import get_user_model
from drf_spectacular.utils import OpenApiResponse, extend_schema
from rest_framework import status
from rest_framework.response import Response
from apps.common.base_views import PublicAPIView

from apps.authentication.api.serializers.phone_login import (
    PhoneLoginRequestSerializer,
    PhoneLoginVerifySerializer,
)
from apps.authentication.api.serializers.token import SignInSerializer
from apps.authentication.models import OTPPurpose
from apps.authentication.services.login_verify_service import (
    LoginVerifyService,
)
from apps.authentication.services.otp_delivery_service import (
    OTPDeliveryService,
    validate_channel,
)
from apps.authentication.services.otp_throttle_service import (
    OTPThrottleService,
)
from apps.common.exceptions import OTPThrottledException
from apps.authentication.services.login_service import sign_in_message
from apps.common.responses import ApiResponse

User = get_user_model()

#: Identical for a known and an unknown number — see E2-S3.
REQUEST_MESSAGE = "If that number is registered, a code has been sent."


@extend_schema(
    tags=["Authentication"],
    summary="Request a phone-login OTP",
    description=(
        "Sends a LOGIN-purpose OTP to the account matching the phone number. "
        "The response is identical whether or not the number is registered."
    ),
    request=PhoneLoginRequestSerializer,
    responses={200: None},
)
class PhoneLoginRequestView(PublicAPIView):

    nullable_data = ("POST",)


    def post(self, request):
        serializer = PhoneLoginRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        channel = validate_channel(serializer.validated_data.get("channel"))

        user = User.objects.filter(
            phone_number=serializer.validated_data["phone_number"]
        ).first()

        if user is not None:
            try:
                OTPThrottleService().check(
                    user=user, purpose=OTPPurpose.LOGIN
                )
                OTPDeliveryService().issue(
                    user=user,
                    purpose=OTPPurpose.LOGIN,
                    channel=channel,
                )
            except OTPThrottledException:
                # Surfacing the throttle here would confirm the number exists.
                pass

        return ApiResponse.success(message=REQUEST_MESSAGE)


@extend_schema(
    tags=["Authentication"],
    summary="Verify a phone-login OTP",
    description=(
        "Exchanges a phone number and code for access/refresh tokens, or "
        "for an MFA challenge when two-step verification is on (see Login)."
    ),
    request=PhoneLoginVerifySerializer,
    responses={200: SignInSerializer},
)
class PhoneLoginVerifyView(PublicAPIView):


    def post(self, request):
        serializer = PhoneLoginVerifySerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        tokens = LoginVerifyService.verify(
            user=serializer.validated_data["user"],
            otp_obj=serializer.validated_data["otp_obj"],
            request=request,
        )

        return ApiResponse.success(
            data=tokens,
            message=sign_in_message(tokens),
            status_code=status.HTTP_200_OK,
        )
