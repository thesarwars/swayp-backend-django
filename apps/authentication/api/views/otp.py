from drf_spectacular.utils import (
    OpenApiExample,
    OpenApiResponse,
    extend_schema,
)
from rest_framework import status
from rest_framework.response import Response
from apps.common.base_views import PublicAPIView
from apps.common.crypto import mask_email

from apps.authentication.api.serializers.otp import (
    ResendOTPSerializer,
    VerifyOTPResponseSerializer,
    VerifyOTPSerializer,
)
from apps.authentication.api.serializers.user_registration import MaskedEmailSerializer
from apps.authentication.models import OTPPurpose
from apps.authentication.services.otp_throttle_service import AddressThrottle
from apps.authentication.services.resend_otp_service import (
    ResendOTPService,
)
from apps.authentication.services.verify_otp_service import (
    VerifyOTPService,
)



#: The same words whether or not an account uses the address (SEC-3).
NEUTRAL_SENT = "If an account uses {email}, a code has been sent to it."

@extend_schema(
    tags=["Authentication"],
    summary="Verify OTP",
    description=(
        "Spend an emailed code. `purpose` defaults to REGISTRATION: the "
        "account is activated and access/refresh tokens are returned. With "
        "`purpose: RESET_PASSWORD` the code is checked and spent, and the "
        "answer is a `reset_token` (with `expires_in` seconds) to send to "
        "/auth/reset-password instead of the code. Nobody is signed in. "
        "LOGIN codes are refused here; they are spent at "
        "/auth/login/phone/verify."
    ),
    request=VerifyOTPSerializer,
    responses={
        200: VerifyOTPResponseSerializer,
        400: OpenApiResponse(description="Invalid OTP."),
    },
    examples=[
        OpenApiExample(
            "Verify OTP",
            value={
                "email": "john@gmail.com",
                "otp": "123456",
            },
            request_only=True,
        ),
    ],
)
class VerifyOTPView(PublicAPIView):

    def post(self, request):
        serializer = VerifyOTPSerializer(data=request.data)

        serializer.is_valid(raise_exception=True)

        user = serializer.validated_data["user"]
        otp_obj = serializer.validated_data["otp_obj"]

        tokens = VerifyOTPService.verify(user, otp_obj)

        return Response(
            {
                "success": True,
                "message": (
                    "Code verified. Set a new password."
                    if otp_obj.purpose == OTPPurpose.RESET_PASSWORD
                    else "Account verified successfully."
                ),
                # purpose is echoed so a client can tell a session (access,
                # refresh) from a reset (reset_token, expires_in) by key.
                "data": {"purpose": otp_obj.purpose, **tokens},
            },
            status=status.HTTP_200_OK,
        )


@extend_schema(
    tags=["Authentication"],
    summary="Resend OTP",
    description="Generate and resend OTP.",
    request=ResendOTPSerializer,
    responses={
        200: MaskedEmailSerializer,
        429: OpenApiResponse(
            description="Too soon or too many: wait Retry-After seconds "
            "(code otp_throttled)."
        ),
    },
    examples=[
        OpenApiExample(
            "Resend OTP",
            value={
                "email": "john@gmail.com",
                "purpose": "REGISTRATION",
            },
            request_only=True,
        )
    ],
)
class ResendOTPView(PublicAPIView):

    def post(self, request):
        serializer = ResendOTPSerializer(
            data=request.data
        )

        serializer.is_valid(raise_exception=True)

        user = serializer.validated_data["user"]
        address = serializer.validated_data["email"]
        purpose = serializer.validated_data["purpose"]

        # Counted per address before anything else, so an unknown address
        # is throttled exactly like a real one (SEC-3).
        AddressThrottle().check(email=address, purpose=purpose)

        if user is not None:
            ResendOTPService.resend(
                user,
                purpose,
                channel=serializer.validated_data.get("channel"),
            )

        email = mask_email(address)

        return Response(
            {
                "success": True,
                "message": NEUTRAL_SENT.format(email=email),
                "data": {"email": email},
            },
            status=status.HTTP_200_OK,
        )
