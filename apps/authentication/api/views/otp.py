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
    VerifyOTPSerializer,
)
from apps.authentication.models import OTPPurpose
from apps.authentication.services.login_verify_service import (
    LoginVerifyService,
)
from apps.authentication.services.resend_otp_service import (
    ResendOTPService,
)
from apps.authentication.services.verify_otp_service import (
    VerifyOTPService,
)


@extend_schema(
    tags=["Authentication"],
    summary="Verify OTP",
    description=(
        "Verify a registration or login OTP and return JWT tokens. One "
        "endpoint for both: `purpose` narrows the search to REGISTRATION or "
        "LOGIN, and leaving it out lets the submitted code decide which flow "
        "it belongs to."
    ),
    request=VerifyOTPSerializer,
    responses={
        200: OpenApiResponse(description="Verified."),
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
        OpenApiExample(
            "Verify a login OTP explicitly",
            value={
                "email": "john@gmail.com",
                "otp": "123456",
                "purpose": "LOGIN",
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

        # The two flows are not interchangeable, which is why this dispatches
        # rather than sharing one path: registration flips is_verified and
        # is_active, while login records the refresh token against a user agent
        # and an IP so the session can be revoked later. The matched code says
        # which of the two the caller is finishing.
        if otp_obj.purpose == OTPPurpose.LOGIN:
            tokens = LoginVerifyService.verify(user, otp_obj, request)
            message = "Login successful."
        else:
            tokens = VerifyOTPService.verify(user, otp_obj)
            message = "Account verified successfully."

        return Response(
            {
                "success": True,
                "message": message,
                # Echoed because one endpoint now answers for two flows and a
                # client that did not send a purpose has no other way to know
                # which one it just completed.
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
        200: OpenApiResponse(description="OTP sent."),
    },
    examples=[
        OpenApiExample(
            "Resend OTP",
            value={
                "email": "john@gmail.com",
                "purpose": "LOGIN",
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

        ResendOTPService.resend(
            user,
            serializer.validated_data["purpose"],
            channel=serializer.validated_data.get("channel"),
        )

        email = mask_email(user.email)

        return Response(
            {
                "success": True,
                "message": f"OTP has been sent to {email}.",
                "data": {"email": email},
            },
            status=status.HTTP_200_OK,
        )
